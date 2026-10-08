"""Fail-closed regression tests for official-task completion (no game input)."""

import copy
import importlib.util
import unittest
from contextlib import ExitStack, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


PLUGIN_PATH = (
    Path(__file__).resolve().parents[1]
    / 'plugins'
    / 'com.searchcat.qqsg.official_task'
    / 'main.py'
)
SPEC = importlib.util.spec_from_file_location('official_completion_plugin', PLUGIN_PATH)
PLUGIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLUGIN)


class CompletionContext:
    """Record state and fail immediately if a test performs unmocked UI input."""

    def __init__(self):
        self.config = {
            'calibrated': True,
            'npc_routes': {
                '奋威中郎将': [23, 7, 16],
                '赵云': [23, 10, 16],
                '李严': [23, 15, 16],
                '糜竺': [23, 20, 16],
            },
            'completion_confirm_scans': 2,
            'completion_recovery_rounds': 2,
            'monitor_interval': 0,
            'runtime_retry_interval': 0,
            'unchanged_retries': 3,
        }
        self.dry_run = False
        self.logs = []
        self.progress = []
        self.watched = []
        self.windows = SimpleNamespace(is_alive=lambda: True)
        self.debug = SimpleNamespace(watch=lambda *args: self.watched.append(args))
        self.storage = SimpleNamespace(write_json=self._write_json)
        self.step = lambda _name: nullcontext()
        forbidden = Mock(side_effect=AssertionError('Tests must not perform real game input'))
        self.keyboard = SimpleNamespace(press=forbidden, key_down=forbidden, key_up=forbidden)
        self.mouse = SimpleNamespace(click=forbidden, move=forbidden)

    def _write_json(self, path, payload):
        self.progress.append((path, copy.deepcopy(payload)))

    def log(self, message, level='info'):
        self.logs.append((level, message))

    def sleep(self, _seconds):
        pass


def task_snapshot(text):
    lines = [
        {'text': line, 'center': [20, 20], 'client_center': [700, 180], 'confidence': 0.95}
        for line in text.splitlines()
    ]
    return text, lines


class OfficialCompletionTests(unittest.TestCase):
    def _run(self, context, texts, evidence=None, needs_attention=True):
        scan = Mock(side_effect=[task_snapshot(text) for text in texts])
        confirm = Mock(return_value=evidence)
        recover = Mock()
        with ExitStack() as stack:
            stack.enter_context(patch.object(PLUGIN, '_scan_task', scan))
            stack.enter_context(patch.object(PLUGIN, '_confirm_official_completion', confirm))
            stack.enter_context(patch.object(PLUGIN, '_recover_gameplay', recover))
            for name in (
                '_navigate_to_target', '_navigate_by_task_click', '_talk_to_nearest_npc',
                '_accept_official_task', '_restore_game_control', '_finish_npc_dialog',
                '_prepare_completion_feedback',
            ):
                stack.enter_context(patch.object(PLUGIN, name, Mock()))
            if needs_attention:
                with self.assertRaises(PLUGIN.OfficialTaskNeedsAttention):
                    PLUGIN.on_start(context)
            else:
                PLUGIN.on_start(context)
        return scan, confirm, recover

    def _assert_attention(self, context, expected_npc):
        self.assertTrue(context.progress)
        path, saved = context.progress[-1]
        self.assertEqual(path, 'progress.json')
        self.assertEqual(saved['status'], 'needs_attention')
        self.assertTrue(saved['reason'])
        self.assertEqual(saved['last_npc'], expected_npc)
        self.assertIn('官爵', saved['last_task_text'])
        self.assertGreater(saved['cycle'], 0)
        self.assertIn('task_transitions', saved)
        self.assertEqual(saved['completed_steps'], saved['task_transitions'])
        self.assertNotIn('completed', [payload['status'] for _, payload in context.progress])

    def test_log_regression_six_empty_scans_cannot_become_completed(self):
        context = CompletionContext()
        scan, _confirm, recover = self._run(
            context, ['高级官爵任务[已完成]\nNPC:糜竺'] + [''] * 6,
        )
        self._assert_attention(context, '糜竺')
        self.assertEqual(scan.call_count, 7)
        self.assertEqual(recover.call_count, 2)

    def test_never_confirmed_acquisition_has_bounded_retries(self):
        context = CompletionContext()
        context.config['task_acquire_retry_scans'] = 2
        context.config['task_acquire_retries'] = 2
        with patch.object(PLUGIN, '_accept_official_task') as accept:
            # Keep acquisition mocked separately so its bounded retry count is observable.
            with patch.object(PLUGIN, '_scan_task', side_effect=[task_snapshot('')] * 6):
                with ExitStack() as stack:
                    for name in ('_navigate_to_target', '_talk_to_nearest_npc', '_restore_game_control'):
                        stack.enter_context(patch.object(PLUGIN, name, Mock()))
                    recover = stack.enter_context(patch.object(PLUGIN, '_recover_gameplay'))
                    confirm = stack.enter_context(patch.object(PLUGIN, '_confirm_official_completion'))
                    with self.assertRaises(PLUGIN.OfficialTaskNeedsAttention):
                        PLUGIN.on_start(context)
        self.assertEqual(accept.call_count, 3)
        recover.assert_not_called()
        confirm.assert_not_called()
        saved = context.progress[-1][1]
        self.assertEqual(saved['status'], 'needs_attention')
        self.assertEqual(saved['last_npc'], '')
        self.assertEqual(saved['task_transitions'], 0)
        self.assertNotIn('completed', [payload['status'] for _, payload in context.progress])

    def test_unrelated_task_after_official_is_unknown_not_success(self):
        context = CompletionContext()
        unrelated = '魔境试炼\nNPC:苍龙\n消灭怪物:魔境天煞0/1'
        scan, _confirm, recover = self._run(
            context, ['高级官爵任务[已完成]\nNPC:糜竺'] + [unrelated] * 6,
        )
        self._assert_attention(context, '糜竺')
        self.assertEqual(scan.call_count, 7)
        self.assertEqual(recover.call_count, 2)

    def test_ocr_noise_after_official_does_not_prove_completion(self):
        context = CompletionContext()
        scan, _confirm, _recover = self._run(
            context,
            ['高级官爵任务[已完成]\nNPC:糜竺'] + ['EK 1.01\n24/5'] * 6,
        )
        self._assert_attention(context, '糜竺')
        self.assertEqual(scan.call_count, 7)

    def test_missing_final_interaction_does_not_consult_positive_evidence(self):
        context = CompletionContext()
        _scan, confirm, _recover = self._run(
            context,
            ['高级官爵任务\nNPC:赵云'] + [''] * 6,
            evidence={'confirmed': True, 'text': '高级官爵任务完成'},
        )
        self._assert_attention(context, '赵云')
        confirm.assert_not_called()

    def test_only_explicit_positive_evidence_permits_completed(self):
        context = CompletionContext()
        scan, confirm, _recover = self._run(
            context,
            ['高级官爵任务[已完成]\nNPC:糜竺'],
            evidence={'confirmed': True, 'text': '高级官爵任务完成', 'frame_ids': ['fresh1', 'fresh2']},
            needs_attention=False,
        )
        self.assertEqual(scan.call_count, 1)
        self.assertEqual(confirm.call_count, 1)
        saved = context.progress[-1][1]
        self.assertEqual(saved['status'], 'completed')
        self.assertEqual(saved['task_transitions'], 0)

    def test_noise_text_does_not_increment_transition_counter(self):
        context = CompletionContext()
        self._run(
            context,
            [
                '高级官爵任务\nNPC:赵云\nEK 1.01',
                '高级官爵任务\nNPC:赵云\nEK 1.02',
                '高级官爵任务\nNPC:赵云\nEK 1.03',
                '高级官爵任务\nNPC:李严\nEK 1.04',
                '高级官爵任务[已完成]\nNPC:糜竺\nEK 1.05',
            ],
            evidence={'confirmed': True, 'text': '高级官爵任务完成'},
            needs_attention=False,
        )
        saved = context.progress[-1][1]
        self.assertEqual(saved['task_transitions'], 2)
        self.assertEqual(saved['completed_steps'], 2)

    def test_completion_flag_only_is_not_a_completed_step(self):
        context = CompletionContext()
        self._run(
            context,
            ['高级官爵任务\nNPC:糜竺', '高级官爵任务[已完成]\nNPC:糜竺'],
            evidence={'confirmed': True, 'text': '高级官爵任务完成'},
            needs_attention=False,
        )
        self.assertEqual(context.progress[-1][1]['task_transitions'], 0)

    def test_terminal_attention_is_not_swallowed_by_stage_runtime_retry(self):
        context = CompletionContext()
        operation = Mock(side_effect=PLUGIN.OfficialTaskNeedsAttention('人工确认'))
        with patch.object(PLUGIN, '_recover_gameplay') as recover:
            with self.assertRaises(PLUGIN.OfficialTaskNeedsAttention):
                PLUGIN._run_step_until_success(context, '确认完成', operation)
        operation.assert_called_once()
        recover.assert_not_called()

    def test_official_signature_ignores_order_spacing_and_unrelated_lines(self):
        self.assertEqual(
            PLUGIN._official_task_signature('高级官爵任务\nNPC:赵云\nEK 1.01', '赵云'),
            PLUGIN._official_task_signature('EK 1.02\nNPC：赵 云\n高级 官爵任务', '赵云'),
        )

    def test_official_signature_uses_canonical_not_noisy_npc(self):
        self.assertEqual(
            PLUGIN._official_task_signature('高级官爵任务\nNPC:李严', '李严'),
            PLUGIN._official_task_signature('高级官爵任务\nIPC:李严\nNPC:李佥', '李严'),
        )

    def test_official_signature_changes_for_real_npc_transition(self):
        self.assertNotEqual(
            PLUGIN._official_task_signature('高级官爵任务\nNPC:赵云', '赵云'),
            PLUGIN._official_task_signature('高级官爵任务\nNPC:李严', '李严'),
        )

    def test_official_signature_changes_for_completion_flag(self):
        self.assertNotEqual(
            PLUGIN._official_task_signature('高级官爵任务\nNPC:糜竺', '糜竺'),
            PLUGIN._official_task_signature('高级官爵任务[已完成]\nNPC:糜竺', '糜竺'),
        )


class OfficialCompletionEvidenceTests(unittest.TestCase):
    def _context(self):
        context = CompletionContext()
        context.config['completion_feedback_region'] = [200, 300, 200, 100]
        context._official_completion_baseline = {
            'clear': True, 'timestamp': 99.0, 'frame_id': 'before_final_enter',
        }
        return context

    @staticmethod
    def _snapshot(frame_id, timestamp, text='高级官爵任务已完成，获得奖励'):
        return SimpleNamespace(id=frame_id, timestamp=timestamp), [{'text': text}]

    def test_no_feedback_region_means_unknown_and_does_not_capture(self):
        context = CompletionContext()
        with patch.object(PLUGIN, '_ocr_text_lines') as scan:
            self.assertIsNone(PLUGIN._confirm_official_completion(context, 100.0))
        scan.assert_not_called()

    def test_dry_run_never_generates_completion_evidence(self):
        context = self._context()
        context.dry_run = True
        with patch.object(PLUGIN, '_ocr_text_lines') as scan:
            self.assertIsNone(PLUGIN._confirm_official_completion(context, 100.0))
        scan.assert_not_called()

    def test_two_fresh_scoped_positive_captures_confirm_completion(self):
        context = self._context()
        with patch.object(PLUGIN, '_ocr_text_lines', side_effect=[
            self._snapshot('frame1', 101.0), self._snapshot('frame2', 102.0),
        ]) as scan:
            evidence = PLUGIN._confirm_official_completion(context, 100.0)
        self.assertTrue(evidence['confirmed'])
        self.assertEqual(evidence['frame_ids'], ['frame1', 'frame2'])
        self.assertEqual(evidence['observed_at'], 102.0)
        self.assertEqual(scan.call_count, 2)
        for call in scan.call_args_list:
            self.assertEqual(call.args, (context, [200, 300, 200, 100]))

    def test_one_positive_capture_followed_by_blank_is_not_enough(self):
        context = self._context()
        with patch.object(PLUGIN, '_ocr_text_lines', side_effect=[
            self._snapshot('frame1', 101.0), self._snapshot('frame2', 102.0, ''),
        ]):
            self.assertIsNone(PLUGIN._confirm_official_completion(context, 100.0))

    def test_negative_first_capture_cannot_be_skipped_until_positive(self):
        context = self._context()
        with patch.object(PLUGIN, '_ocr_text_lines', side_effect=[
            self._snapshot('frame1', 101.0, ''), self._snapshot('frame2', 102.0),
        ]) as scan:
            self.assertIsNone(PLUGIN._confirm_official_completion(context, 100.0))
        self.assertEqual(scan.call_count, 1)

    def test_duplicate_frame_id_cannot_count_as_two_fresh_readings(self):
        context = self._context()
        with patch.object(PLUGIN, '_ocr_text_lines', side_effect=[
            self._snapshot('same', 101.0), self._snapshot('same', 102.0),
        ]):
            self.assertIsNone(PLUGIN._confirm_official_completion(context, 100.0))

    def test_capture_at_or_before_final_interaction_is_rejected(self):
        for timestamp in (99.0, 100.0):
            with self.subTest(timestamp=timestamp):
                context = self._context()
                with patch.object(PLUGIN, '_ocr_text_lines', return_value=self._snapshot('old', timestamp)):
                    self.assertIsNone(PLUGIN._confirm_official_completion(context, 100.0))

    def test_second_capture_must_be_newer_than_first(self):
        for timestamp in (100.5, 101.0):
            with self.subTest(timestamp=timestamp):
                context = self._context()
                with patch.object(PLUGIN, '_ocr_text_lines', side_effect=[
                    self._snapshot('frame1', 101.0), self._snapshot('frame2', timestamp),
                ]):
                    self.assertIsNone(PLUGIN._confirm_official_completion(context, 100.0))

    def test_invalid_timestamp_or_frame_id_is_rejected(self):
        for frame_id, timestamp in (
            ('frame1', float('nan')), ('frame1', float('inf')), ('frame1', None),
            ('frame1', True), ('', 101.0), (1, 101.0),
        ):
            with self.subTest(frame_id=frame_id, timestamp=timestamp):
                context = self._context()
                with patch.object(PLUGIN, '_ocr_text_lines', return_value=self._snapshot(frame_id, timestamp)):
                    self.assertIsNone(PLUGIN._confirm_official_completion(context, 100.0))

    def test_generic_rewards_and_other_task_success_are_not_evidence(self):
        for text in ('获得奖励', '高级任务已完成', '魔境试炼任务完成', '经验+50000'):
            with self.subTest(text=text):
                self.assertFalse(PLUGIN._completion_feedback_text(text, ['官爵任务完成']))

    def test_negative_and_confirmation_prompt_are_not_evidence(self):
        for text in (
            '官爵任务尚未完成', '官爵任务未完成', '是否完成官爵任务？',
            '不能完成官爵任务', '奖励预览：完成官爵任务',
            '没有完成官爵任务', '官爵任务没有完成', '官爵任务未完成官爵任务',
            '官爵任务未完成官爵任务已完成', '官爵任务成功完成官爵任务但未获得奖励',
            '请成功完成官爵任务', '成功完成官爵任务后领取奖励',
            '若官爵任务已完成则领取奖励', '官爵任务已完成吗？',
        ):
            with self.subTest(text=text):
                self.assertFalse(PLUGIN._completion_feedback_text(
                    text, ['官爵任务已完成', '成功完成官爵任务', '已完成官爵任务'],
                ))

    def test_tracker_complete_flag_is_only_ready_for_delivery(self):
        self.assertTrue(PLUGIN._official_ready_for_delivery('高级官爵任务[已完成]\nNPC:糜竺'))
        self.assertFalse(PLUGIN._official_ready_for_delivery('高级官爵任务\n魔境试炼[已完成]'))
        self.assertFalse(PLUGIN._official_ready_for_delivery('高级官爵任务\nNPC:糜竺'))

    def test_feedback_region_overlapping_tracker_is_rejected(self):
        context = self._context()
        context.config['completion_feedback_region'] = [520, 70, 270, 430]
        with patch.object(PLUGIN, '_ocr_text_lines') as scan:
            with self.assertRaises(ValueError):
                PLUGIN._confirm_official_completion(context, 100.0)
        scan.assert_not_called()

    def test_feedback_markers_cannot_be_generic_or_negative(self):
        for markers in (['获得奖励'], ['已完成'], ['官爵任务尚未完成'], [], '官爵任务完成'):
            with self.subTest(markers=markers):
                context = self._context()
                context.config['completion_feedback_markers'] = markers
                with patch.object(PLUGIN, '_ocr_text_lines') as scan:
                    with self.assertRaises(ValueError):
                        PLUGIN._confirm_official_completion(context, 100.0)
                scan.assert_not_called()

    def test_malformed_roi_is_rejected_before_capture(self):
        for region in ([200, 300, 0, 100], [-1, 300, 200, 100], [200, 300, True, 100], [1, 2]):
            with self.subTest(region=region):
                context = self._context()
                context.config['completion_feedback_region'] = region
                with patch.object(PLUGIN, '_ocr_text_lines') as scan:
                    with self.assertRaises(ValueError):
                        PLUGIN._confirm_official_completion(context, 100.0)
                scan.assert_not_called()

    def test_missing_clear_baseline_is_not_completion_evidence(self):
        context = self._context()
        del context._official_completion_baseline
        with patch.object(PLUGIN, '_ocr_text_lines') as scan:
            self.assertIsNone(PLUGIN._confirm_official_completion(context, 100.0))
        scan.assert_not_called()

    def test_existing_successful_message_baseline_is_not_completion_evidence(self):
        context = self._context()
        context._official_completion_baseline['clear'] = False
        with patch.object(PLUGIN, '_ocr_text_lines') as scan:
            self.assertIsNone(PLUGIN._confirm_official_completion(context, 100.0))
        scan.assert_not_called()

    def test_new_capture_cannot_reuse_baseline_frame(self):
        context = self._context()
        with patch.object(PLUGIN, '_ocr_text_lines', side_effect=[
            self._snapshot('before_final_enter', 101.0), self._snapshot('frame2', 102.0),
        ]):
            self.assertIsNone(PLUGIN._confirm_official_completion(context, 100.0))

    def test_prepare_arms_from_a_nonempty_pre_delivery_dialog(self):
        context = self._context()
        with patch.object(PLUGIN, '_ocr_text_lines', return_value=self._snapshot(
            'new_baseline', 99.5, '将军正在等你的回复，按回车继续对话',
        )):
            PLUGIN._prepare_completion_feedback(context)
        baseline = context._official_completion_baseline
        self.assertTrue(baseline['clear'])
        self.assertEqual(baseline['frame_id'], 'new_baseline')
        self.assertEqual(baseline['timestamp'], 99.5)

    def test_prepare_disarms_empty_or_preexisting_successful_message(self):
        for text in ('', '高级官爵任务已完成，获得奖励'):
            with self.subTest(text=text):
                context = self._context()
                with patch.object(PLUGIN, '_ocr_text_lines', return_value=self._snapshot('baseline', 99.5, text)):
                    PLUGIN._prepare_completion_feedback(context)
                self.assertFalse(context._official_completion_baseline['clear'])

    def test_prepare_capture_failure_disarms_previous_baseline(self):
        context = self._context()
        with patch.object(PLUGIN, '_ocr_text_lines', side_effect=RuntimeError('截图失败')):
            PLUGIN._prepare_completion_feedback(context)
        self.assertIsNone(context._official_completion_baseline)

    def test_baseline_after_final_interaction_is_not_eligible(self):
        context = self._context()
        context._official_completion_baseline['timestamp'] = 100.5
        with patch.object(PLUGIN, '_ocr_text_lines') as scan:
            self.assertIsNone(PLUGIN._confirm_official_completion(context, 100.0))
        scan.assert_not_called()

    def test_feedback_read_failure_is_unknown_not_runtime_retry(self):
        context = self._context()
        with patch.object(PLUGIN, '_ocr_text_lines', side_effect=RuntimeError('OCR 暂时失败')):
            self.assertIsNone(PLUGIN._confirm_official_completion(context, 100.0))


if __name__ == '__main__':
    unittest.main()
