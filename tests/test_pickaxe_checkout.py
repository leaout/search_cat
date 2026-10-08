"""Exercise actual checkout orchestration with mocked UI/SDK observations."""
import importlib.util
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch


MAIN = Path(__file__).resolve().parents[1] / 'plugins/com.searchcat.qqsg.mining/main.py'
SPEC = importlib.util.spec_from_file_location('checkout_main', MAIN)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.context = Mock()
        self.context.dry_run = False
        self.context.config = {
            'pickaxe_character_id': 'role-one', 'pickaxe_wage_budget': 5,
            'pickaxe_auto_equip_enabled': True, 'pickaxe_inventory_key': 'b',
            'pickaxe_inventory_close_key': 'b',
            'pickaxe_inventory_region': [100, 100, 200, 200],
            'pickaxe_tooltip_region': [300, 100, 200, 200],
        }
        self.context.windows.activate.return_value = {'active': True}
        self.ledger = {}
        self.context.storage.read_json.side_effect = lambda path, default: deepcopy(self.ledger.get(path, default))
        self.context.storage.write_json.side_effect = lambda path, value: self.ledger.update({path: deepcopy(value)})
        self.shop = [{'text': '推荐', 'center': [314, 262]},
                     {'text': '商店物品', 'center': [402, 262]}]
        self.detail = [{'text': '中级精钢矿锄'}, {'text': '花费工资：5'}, {'text': '等级限制：70'}]
        self.receipt = [{'text': '兑换成功，获得道具中级精钢矿锄1个，失去工资5'}]

    def observations(self):
        # initial shop, after tab, after category, wages, detail, quantity, two field crops,
        # no preexisting receipt, actual receipt, changed wages.
        return [self.shop, self.shop, self.shop, [{'text': '我的工资：11225点'}],
                self.detail, [{'text': '选择数量：', 'center': [874, 480]}],
                [{'text': '1'}], [{'text': '1'}], [], self.receipt, [{'text': '我的工资：11220点'}]]

    def test_success_spends_once_then_equips(self):
        with patch.object(MODULE, '_shop_scan', side_effect=self.observations()), \
                patch.object(MODULE, '_try_equip_spare_pickaxe', return_value=True) as equip:
            self.assertTrue(MODULE._try_buy_middle_pickaxe(self.context))
        record = next(iter(self.ledger.values()))
        self.assertEqual(record['spent'], 5)
        self.assertIsNone(record['pending'])
        equip.assert_called_once_with(self.context)
        clicks = [call.args for call in self.context.mouse.click.call_args_list]
        self.assertEqual(clicks[:5], [(402, 262), (316, 321), (321, 343), (619, 473), (949, 513)])
        self.assertEqual(clicks.count((1001, 519)), 1)
        with self.assertRaises(ValueError):
            MODULE._try_buy_middle_pickaxe(self.context)

    def test_quantity_crop_covers_left_aligned_one_in_screenshot(self):
        with patch.object(MODULE, '_shop_scan', side_effect=self.observations()) as scan, \
                patch.object(MODULE, '_try_equip_spare_pickaxe', return_value=True):
            self.assertTrue(MODULE._try_buy_middle_pickaxe(self.context))
        region = scan.call_args_list[6].args[1]
        self.assertEqual(region, (849, 508, 100, 23))
        x, y, width, height = region
        self.assertTrue(x <= 867 < x + width and y <= 518 < y + height)

    def test_wrong_product_does_not_reserve_or_checkout(self):
        observations = self.observations()[:4] + [[{'text': '高级精钢矿锄'}, {'text': '花费工资：10'}]] * 2
        with patch.object(MODULE, '_shop_scan', side_effect=observations):
            with self.assertRaises(RuntimeError):
                MODULE._try_buy_middle_pickaxe(self.context)
        self.assertEqual(self.ledger, {})
        self.assertNotIn((949, 513), [call.args for call in self.context.mouse.click.call_args_list])

    def test_ambiguous_result_keeps_pending_and_blocks_second_checkout(self):
        observations = self.observations()[:9] + [[], [{'text': '我的工资：11220点'}]] * 3
        with patch.object(MODULE, '_shop_scan', side_effect=observations), \
                patch.object(MODULE, '_try_equip_spare_pickaxe') as equip:
            self.assertFalse(MODULE._try_buy_middle_pickaxe(self.context))
        self.assertTrue(next(iter(self.ledger.values()))['pending'])
        self.assertEqual([call.args for call in self.context.mouse.click.call_args_list].count((1001, 519)), 1)
        equip.assert_not_called()
        with self.assertRaises(ValueError):
            MODULE._try_buy_middle_pickaxe(self.context)

    def test_preexisting_success_dialog_blocks_submission(self):
        observations = self.observations()[:9]
        observations[-1] = self.receipt
        with patch.object(MODULE, '_shop_scan', side_effect=observations):
            with self.assertRaises(RuntimeError):
                MODULE._try_buy_middle_pickaxe(self.context)
        self.assertEqual(self.ledger, {})

    def test_wrong_quantity_does_not_spend(self):
        observations = self.observations()[:7]
        observations[-1] = [{'text': '10'}]
        with patch.object(MODULE, '_shop_scan', side_effect=observations):
            with self.assertRaises(RuntimeError):
                MODULE._try_buy_middle_pickaxe(self.context)
        self.assertEqual(self.ledger, {})

    def test_second_quantity_check_failure_does_not_spend(self):
        observations = self.observations()[:8]
        observations[-1] = [{'text': '10'}]
        with patch.object(MODULE, '_shop_scan', side_effect=observations):
            with self.assertRaises(RuntimeError):
                MODULE._try_buy_middle_pickaxe(self.context)
        self.assertEqual(self.ledger, {})

    def test_incomplete_old_receipt_also_blocks_submission(self):
        observations = self.observations()[:9]
        observations[-1] = [{'text': '兑换成功，获得道具'}, {'text': '其他字段漏读'}]
        with patch.object(MODULE, '_shop_scan', side_effect=observations):
            with self.assertRaises(RuntimeError):
                MODULE._try_buy_middle_pickaxe(self.context)
        self.assertEqual(self.ledger, {})

    def test_dry_run_does_not_touch_ui_or_ledger(self):
        self.context.dry_run = True
        self.assertFalse(MODULE._try_buy_middle_pickaxe(self.context))
        self.context.mouse.click.assert_not_called()
        self.context.storage.write_json.assert_not_called()

    def test_buy_without_monitor_or_equipment_is_rejected_before_start(self):
        self.context.config['pickaxe_auto_buy_enabled'] = True
        with self.assertRaises(ValueError):
            MODULE.on_start(self.context)
        self.context.windows.current.assert_not_called()
        self.context.mouse.click.assert_not_called()

    def test_activity_key_i_and_relative_exchange_entry(self):
        activity = [{'text': '游戏活动展示', 'center': [411, 257]},
                    {'text': '活跃度', 'center': [654, 296]}]
        observations = [[], activity, self.shop] + self.observations()[1:]
        with patch.object(MODULE, '_shop_scan', side_effect=observations), \
                patch.object(MODULE, '_try_equip_spare_pickaxe', return_value=True):
            MODULE._try_buy_middle_pickaxe(self.context)
        self.context.keyboard.press.assert_called_once_with('i', mode='foreground')
        self.assertEqual(self.context.mouse.click.call_args_list[0].args, (939, 406))

    def test_empty_ocr_without_prior_low_durability_cannot_trigger_purchase(self):
        context = self.context
        context.config.update({'pickaxe_monitor_enabled': True, 'pickaxe_auto_equip_enabled': True,
                               'pickaxe_auto_buy_enabled': True, 'pickaxe_region': [10, 10, 180, 40]})
        context.windows.current.return_value = {'hwnd': 123}
        context.ocr.recognize.side_effect = [[]] * 4 + [[{'text': '360/360'}]]

        def spare(current):
            current._pickaxe_spare_state = 'absent'
            return False

        with patch.object(MODULE, '_try_equip_spare_pickaxe', side_effect=spare), \
                patch.object(MODULE, '_try_buy_middle_pickaxe') as buy:
            MODULE._ensure_pickaxe_ready(context)
        buy.assert_not_called()

    def test_confirmed_low_durability_disappearance_allows_one_purchase(self):
        context = self.context
        context.config.update({'pickaxe_monitor_enabled': True, 'pickaxe_auto_equip_enabled': True,
                               'pickaxe_auto_buy_enabled': True, 'pickaxe_region': [10, 10, 180, 40]})
        context._pickaxe_last_good = (2, 360)
        context.windows.current.return_value = {'hwnd': 123}
        context.ocr.recognize.side_effect = [[]] * 4 + [[{'text': '360/360'}]]

        def spare(current):
            current._pickaxe_spare_state = 'absent'
            return False

        with patch.object(MODULE, '_try_equip_spare_pickaxe', side_effect=spare), \
                patch.object(MODULE, '_try_buy_middle_pickaxe', return_value=True) as buy:
            MODULE._ensure_pickaxe_ready(context)
        buy.assert_called_once_with(context)
