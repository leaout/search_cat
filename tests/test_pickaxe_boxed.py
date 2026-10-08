"""Keep boxed purchases separate from verified, equipped mining tools."""

import importlib.util
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

from plugin_platform import qqsg_pickaxe_shop as shop


MAIN = Path(__file__).resolve().parents[1] / 'plugins/com.searchcat.qqsg.mining/main.py'
SPEC = importlib.util.spec_from_file_location('boxed_pickaxe_main', MAIN)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


USE_WARNING = [
    {'text': '如果背包空间不足或奖励堆叠达到上限，多余的道具会通过邮箱发放'},
    {'text': '多余的装备会无法获取，确定要使用吗？'},
    {'text': '确定'},
    {'text': '取消'},
]


class PackageUseWarningTests(unittest.TestCase):
    def test_screenshot_warning_is_a_pending_package_use(self):
        self.assertTrue(shop.package_use_pending(USE_WARNING))

    def test_each_risk_phrase_with_explicit_use_question_is_detected(self):
        for risk in ('背包空间', '奖励堆叠', '邮箱发放', '无法获取', '多余的装备'):
            with self.subTest(risk=risk):
                self.assertTrue(shop.package_use_pending([
                    {'text': risk}, {'text': '确定要使用吗？'},
                ]))

    def test_split_lines_and_spaces_do_not_hide_the_warning(self):
        self.assertTrue(shop.package_use_pending([
            {'text': '如 果 背 包 空 间不足'}, {'text': '确定要'}, {'text': '使用吗？'},
        ]))

    def test_two_risks_and_confirm_cancel_detect_partial_ocr(self):
        self.assertTrue(shop.package_use_pending([
            {'text': '背包空间不足'}, {'text': '奖励堆叠达到上限'},
            {'text': '确定'}, {'text': '取消'},
        ]))

    def test_generic_confirmation_is_not_a_package_warning(self):
        for items in ([], [{'text': '确定要使用吗？'}], [{'text': '确定'}, {'text': '取消'}],
                      [{'text': '背包空间不足'}, {'text': '确定'}, {'text': '取消'}],
                      [{'text': '背包空间不足'}, {'text': '奖励堆叠达到上限'}]):
            with self.subTest(items=items):
                self.assertFalse(shop.package_use_pending(items))


class BoxedPurchaseLedgerTests(unittest.TestCase):
    def setUp(self):
        self.context = Mock()
        self.context.dry_run = False
        self.context.config = {'pickaxe_character_id': 'boxed-role', 'pickaxe_wage_budget': 20}
        self.records = {}
        self.context.storage.read_json.side_effect = lambda path, default: deepcopy(self.records.get(path, default))
        self.context.storage.write_json.side_effect = lambda path, value: self.records.update({path: deepcopy(value)})

    def confirmed_box(self):
        transaction = MODULE._reserve_pickaxe_purchase(self.context, 100)
        self.assertTrue(MODULE._confirm_pickaxe_purchase(self.context, transaction, True))
        return transaction, MODULE._pickaxe_purchase_path(self.context)

    def test_receipt_records_boxed_fulfillment_instead_of_equipment(self):
        transaction, path = self.confirmed_box()
        ledger = self.records[path]
        self.assertEqual(ledger['spent'], 5)
        self.assertIsNone(ledger['pending'])
        self.assertEqual(ledger['unfulfilled']['id'], transaction)
        self.assertEqual(ledger['unfulfilled']['stage'], 'boxed')

    def test_confirmed_but_unfulfilled_box_blocks_another_reservation(self):
        self.confirmed_box()
        with self.assertRaises(ValueError):
            MODULE._reserve_pickaxe_purchase(self.context, 100)
        self.assertEqual(next(iter(self.records.values()))['spent'], 5)

    def test_unfulfilled_box_blocks_checkout_before_any_game_input(self):
        self.confirmed_box()
        with self.assertRaises(ValueError):
            MODULE._try_buy_middle_pickaxe(self.context)
        self.context.windows.activate.assert_not_called()
        self.context.keyboard.press.assert_not_called()
        self.context.mouse.click.assert_not_called()

    def test_boxed_fulfillment_blocks_repurchase_after_process_restart(self):
        self.confirmed_box()
        restarted = Mock()
        restarted.dry_run = False
        restarted.config = deepcopy(self.context.config)
        restarted.storage.read_json.side_effect = lambda path, default: deepcopy(self.records.get(path, default))
        restarted.storage.write_json.side_effect = lambda path, value: self.records.update({path: deepcopy(value)})
        with self.assertRaises(ValueError):
            MODULE._reserve_pickaxe_purchase(restarted, 100)
        with self.assertRaises(ValueError):
            MODULE._try_buy_middle_pickaxe(restarted)
        restarted.keyboard.press.assert_not_called()
        restarted.mouse.click.assert_not_called()
        restarted.storage.write_json.assert_not_called()

    def test_positive_fresh_durability_clears_only_unfulfilled_state(self):
        transaction, path = self.confirmed_box()
        MODULE._finish_pickaxe_fulfillment(self.context, (334, 360))
        ledger = self.records[path]
        self.assertFalse(ledger.get('unfulfilled'))
        self.assertEqual(ledger['spent'], 5)
        self.assertEqual(ledger['last_confirmed']['id'], transaction)
        MODULE._reserve_pickaxe_purchase(self.context, 100)

    def test_invalid_or_depleted_durability_cannot_clear_box(self):
        transaction, path = self.confirmed_box()
        for reading in (None, (0, 360), (-1, 360), (361, 360), (12, 2040),
                        [360, 360], (True, 360), ('360', 360), (360,), (360, 360, 1)):
            with self.subTest(reading=reading):
                MODULE._finish_pickaxe_fulfillment(self.context, reading)
                self.assertEqual(self.records[path]['unfulfilled']['id'], transaction)

    def test_mismatched_fulfillment_id_cannot_clear_box(self):
        transaction, path = self.confirmed_box()
        self.records[path]['last_confirmed']['id'] = 'different-transaction'
        with self.assertRaises(ValueError):
            MODULE._finish_pickaxe_fulfillment(self.context, (360, 360))
        self.assertEqual(self.records[path]['unfulfilled']['id'], transaction)

    def test_wrong_fulfillment_stage_cannot_clear_box(self):
        transaction, path = self.confirmed_box()
        self.records[path]['unfulfilled']['stage'] = 'unknown'
        with self.assertRaises(ValueError):
            MODULE._finish_pickaxe_fulfillment(self.context, (360, 360))
        self.assertEqual(self.records[path]['unfulfilled']['id'], transaction)

    def test_no_character_identity_does_not_access_purchase_ledger(self):
        self.context.config['pickaxe_character_id'] = ''
        MODULE._finish_pickaxe_fulfillment(self.context, (360, 360))
        self.context.storage.read_json.assert_not_called()
        self.context.storage.write_json.assert_not_called()

    def test_unknown_checkout_result_does_not_create_boxed_success(self):
        transaction = MODULE._reserve_pickaxe_purchase(self.context, 100)
        self.assertFalse(MODULE._confirm_pickaxe_purchase(self.context, transaction, False))
        ledger = next(iter(self.records.values()))
        self.assertEqual(ledger['pending']['id'], transaction)
        self.assertFalse(ledger.get('unfulfilled'))


class BoxedSpareInputTests(unittest.TestCase):
    def setUp(self):
        self.context = Mock()
        self.context.dry_run = False
        self.context.config = {
            'pickaxe_inventory_region': [100, 200, 200, 300],
            'pickaxe_tooltip_region': [300, 200, 200, 300],
            'pickaxe_inventory_key': 'b', 'pickaxe_inventory_close_key': 'b',
        }
        self.context.windows.activate.return_value = {'active': True}
        self.context.vision.find_image.return_value = type('Match', (), {'found': True, 'center': [20, 30]})()
        self.context.ocr.recognize.return_value = [{'text': '中级精钢矿锄'}]

    def test_existing_package_warning_prevents_all_keyboard_and_mouse_input(self):
        with patch.object(MODULE, '_shop_scan', return_value=USE_WARNING):
            self.assertFalse(MODULE._try_equip_spare_pickaxe(self.context))
        self.assertEqual(self.context._pickaxe_spare_state, 'package_use_pending')
        self.context.keyboard.press.assert_not_called()
        self.context.mouse.click.assert_not_called()
        self.context.mouse.move.assert_not_called()

    def test_warning_after_use_is_preserved_and_not_auto_confirmed(self):
        def observe(_context, *_args, **_kwargs):
            if self.context.mouse.click.call_count:
                return USE_WARNING
            if self.context.keyboard.press.call_count:
                return [{'text': '物品'}]
            return []

        with patch.object(MODULE, '_shop_scan', side_effect=observe):
            MODULE._try_equip_spare_pickaxe(self.context)
        self.assertEqual(self.context._pickaxe_spare_state, 'package_use_pending')
        self.assertEqual(self.context.mouse.click.call_count, 2)
        self.context.keyboard.press.assert_called_once_with('b', mode='foreground')
        self.assertNotIn((574, 572), [call.args for call in self.context.mouse.click.call_args_list])

    def test_template_miss_is_local_not_proof_of_absent_inventory(self):
        self.context.vision.find_image.return_value = type('Match', (), {'found': False})()

        def observe(_context, *_args, **_kwargs):
            return [{'text': '物品'}] if self.context.keyboard.press.call_count else []

        with patch.object(MODULE, '_shop_scan', side_effect=observe):
            self.assertFalse(MODULE._try_equip_spare_pickaxe(self.context))
        self.assertEqual(self.context._pickaxe_spare_state, 'not_found_here')
        self.context.mouse.click.assert_not_called()

    def test_single_page_template_miss_cannot_trigger_purchase(self):
        self.context.config.update({'pickaxe_monitor_enabled': True, 'pickaxe_auto_equip_enabled': True,
                                    'pickaxe_auto_buy_enabled': True, 'pickaxe_region': [10, 10, 180, 40]})
        self.context.windows.current.return_value = {'hwnd': 123}
        self.context.ocr.recognize.side_effect = [
            [{'text': '0/360'}], [{'text': '0/360'}], [{'text': '360/360'}],
        ]

        def no_match(current):
            current._pickaxe_spare_state = 'not_found_here'
            return False

        with patch.object(MODULE, '_try_equip_spare_pickaxe', side_effect=no_match), \
                patch.object(MODULE, '_try_buy_middle_pickaxe') as buy:
            MODULE._ensure_pickaxe_ready(self.context)
        buy.assert_not_called()


if __name__ == '__main__':
    unittest.main()
