"""Pure screenshot calibration tests; no capture, OCR engine, or real UI input."""
import unittest

from plugin_platform.qqsg_pickaxe_shop import (
    compact,
    middle_pickaxe_detail,
    panel_anchor,
    purchase_receipt,
    purchase_session_key,
    shop_point,
    shop_region,
    wage_balance,
)


def text_item(text: str, point=None) -> dict:
    item = {'text': text}
    if point is not None:
        item['center'] = point
    return item


def item_center(item: dict):
    return item.get('center')


class QQSGPickaxeShopTests(unittest.TestCase):
    def test_purchase_session_key_rejects_empty_identity(self):
        for identity in ('', ' ', '\t\r\n'):
            with self.subTest(identity=identity):
                with self.assertRaises(ValueError):
                    purchase_session_key(identity)

    def test_purchase_session_key_trims_identity_and_is_stable(self):
        expected = purchase_session_key('抚琴退敌-船长号')
        self.assertEqual(purchase_session_key('  抚琴退敌-船长号\t\n'), expected)
        self.assertEqual(purchase_session_key('抚琴退敌-船长号'), expected)

    def test_purchase_session_key_distinguishes_characters(self):
        self.assertNotEqual(purchase_session_key('抚琴退敌-船长号'),
                            purchase_session_key('抚琴退敌-小一宝'))
        self.assertNotEqual(purchase_session_key('抚琴退敌-船长号'),
                            purchase_session_key('其他服务器-船长号'))

    def test_purchase_session_key_does_not_expose_plaintext_identity(self):
        identity = '抚琴退敌-船长号-private-user-123'
        key = purchase_session_key(identity)
        self.assertRegex(key, r'^mining-role-[0-9a-f]{24}$')
        self.assertNotIn(identity, key)
        self.assertNotIn('船长号', key)
        self.assertNotIn('private-user', key)

    def test_shop_anchor_matches_supplied_client_screenshot(self):
        items = [text_item('￥工资商店', (314, 213)),
                 text_item('商店物品', (402, 262)),
                 text_item('推荐', (314, 262)),
                 text_item('消耗品', (316, 321)),
                 text_item('经验&抗性', (321, 343))]
        self.assertEqual(panel_anchor(items, 'shop', item_center), (314, 213))

    def test_shop_translation_is_not_a_fixed_desktop_position(self):
        items = [text_item('工资商店', (74, 113)),
                 text_item('商店物品', (162, 162)),
                 text_item('经验&抗性', (81, 243))]
        anchor = panel_anchor(items, 'shop', item_center)
        self.assertEqual(anchor, (74, 113))
        self.assertEqual(shop_point(anchor, 'middle_pickaxe'), (379, 373))

    def test_activity_anchor_uses_title_and_independent_labels(self):
        items = [text_item('游戏活动展示', (412, 261)),
                 text_item('今日福利', (314, 300)),
                 text_item('活跃度', (655, 300))]
        self.assertEqual(panel_anchor(items, 'activity', item_center), (412, 261))

    def test_one_label_or_duplicate_label_is_not_enough(self):
        for items in ([text_item('工资商店', (314, 213))],
                      [text_item('工资商店', (314, 213)),
                       text_item('工资商店', (315, 214))],
                      [text_item('游戏活动展示', (412, 261))]):
            with self.subTest(items=items):
                panel = 'activity' if items[0]['text'] == '游戏活动展示' else 'shop'
                self.assertIsNone(panel_anchor(items, panel, item_center))

    def test_two_secondary_shop_labels_can_locate_panel(self):
        items = [text_item('商店物品', (402, 262)),
                 text_item('消耗品', (316, 321))]
        self.assertEqual(panel_anchor(items, 'shop', item_center), (314, 213))

    def test_anchors_from_different_positions_fail_closed(self):
        items = [text_item('工资商店', (314, 213)),
                 text_item('商店物品', (502, 362))]
        self.assertIsNone(panel_anchor(items, 'shop', item_center))

    def test_scaled_shop_layout_is_not_used_as_native_translation(self):
        items = [text_item('工资商店', (314, 213)),
                 text_item('商店物品', (490, 311)),
                 text_item('经验&抗性', (328, 473))]
        self.assertIsNone(panel_anchor(items, 'shop', item_center))

    def test_thirty_percent_scale_is_rejected_with_title_and_recommendation(self):
        items = [text_item('工资商店', (314, 213)),
                 text_item('推荐', (314, 277))]
        self.assertIsNone(panel_anchor(items, 'shop', item_center))

    def test_missing_geometry_and_unrelated_text_do_not_anchor_panel(self):
        items = [text_item('工资商店'), text_item('推荐', (314, 262)),
                 text_item('聊天：工资商店', (314, 213)),
                 text_item('商城物品', (402, 262))]
        self.assertIsNone(panel_anchor(items, 'shop', item_center))

    def test_isolated_false_anchor_does_not_override_matching_pair(self):
        items = [text_item('工资商店', (30, 30)),
                 text_item('商店物品', (402, 262)),
                 text_item('消耗品', (316, 321)),
                 text_item('经验&抗性', (321, 343))]
        self.assertEqual(panel_anchor(items, 'shop', item_center), (314, 213))

    def test_all_shop_points_are_client_coordinates(self):
        anchor = (314, 213)
        expected = {'shop_tab': (402, 262), 'consumables': (316, 321),
                    'experience': (321, 343), 'middle_pickaxe': (619, 473),
                    'exchange': (949, 513), 'close': (1007, 225)}
        for name, point in expected.items():
            with self.subTest(name=name):
                self.assertEqual(shop_point(anchor, name), point)

    def test_shop_regions_cover_only_expected_panel_sections(self):
        anchor = (314, 213)
        expected = {'wages': (719, 243, 175, 32),
                    'detail': (674, 485, 330, 140),
                    'receipt': (494, 425, 240, 168)}
        for name, region in expected.items():
            with self.subTest(name=name):
                self.assertEqual(shop_region(anchor, name), region)
        # The dialog crop excludes the old purchase messages in bottom-left chat.
        x, y, width, height = shop_region(anchor, 'receipt')
        self.assertFalse(x <= 100 < x + width and y <= 783 < y + height)

    def test_unknown_point_or_region_is_not_silently_defaulted(self):
        with self.assertRaises(KeyError):
            shop_point((314, 213), 'unknown')
        with self.assertRaises(KeyError):
            shop_region((314, 213), 'unknown')

    def test_compact_normalizes_ocr_spaces_and_colon(self):
        self.assertEqual(compact(' 我的工资 ： 11225 点\n'), '我的工资:11225点')
        self.assertEqual(compact(None), '')

    def test_wage_balance_before_and_after_single_purchase(self):
        self.assertEqual(wage_balance([text_item('我的工资： 11225 点')]), 11225)
        self.assertEqual(wage_balance([text_item('我的工资:11220点')]), 11220)
        self.assertEqual(wage_balance([text_item('我的工资 0 点')]), 0)

    def test_wage_balance_accepts_heading_digits_and_unit_as_separate_items(self):
        self.assertEqual(wage_balance([text_item('我的工资：'), text_item('12125'),
                                       text_item('点')]), 12125)

    def test_wage_balance_rejects_two_conflicting_split_values(self):
        self.assertIsNone(wage_balance([
            text_item('我的工资：'), text_item('12125'), text_item('点'),
            text_item('我的工资：'), text_item('12120'), text_item('点')]))

    def test_wage_balance_rejects_missing_or_conflicting_values(self):
        self.assertIsNone(wage_balance([text_item('花费工资：5')]))
        self.assertIsNone(wage_balance([text_item('我的工资：11225')]))
        self.assertIsNone(wage_balance([text_item('我的工资：11225点'),
                                       text_item('我的工资：11220点')]))
        self.assertEqual(wage_balance([text_item('我的工资：11225点'),
                                      text_item('我的工资：11225点')]), 11225)

    def test_middle_pickaxe_detail_accepts_correct_item_price_and_level(self):
        items = [text_item('中级精钢矿锄'), text_item('花费工资：5'),
                 text_item('等级限制：70'), text_item('70-109级玩家可装备')]
        self.assertTrue(middle_pickaxe_detail(items))

    def test_wrong_item_price_or_level_cannot_authorize_checkout(self):
        for name, price, level in [('高级精钢矿锄', 5, 70),
                                   ('中级精钢矿锄', 10, 70),
                                   ('中级精钢矿锄', 15, 70),
                                   ('中级精钢矿锄', 50, 70),
                                   ('中级精钢矿锄', 500, 70),
                                   ('中级精钢矿锄', 5, 110),
                                   ('中级精钢矿锄', 5, 700)]:
            with self.subTest(name=name, price=price, level=level):
                self.assertFalse(middle_pickaxe_detail([
                    text_item(name), text_item(f'花费工资：{price}'),
                    text_item(f'等级限制：{level}')]))

    def test_incomplete_detail_does_not_authorize_checkout(self):
        for items in ([], [text_item('中级精钢矿锄')],
                      [text_item('中级精钢矿锄'), text_item('花费工资：5')],
                      [text_item('中级精钢矿锄'), text_item('等级限制：70')]):
            with self.subTest(items=items):
                self.assertFalse(middle_pickaxe_detail(items))

    def test_conflicting_detail_prices_are_not_a_valid_five_wage_item(self):
        self.assertFalse(middle_pickaxe_detail([
            text_item('中级精钢矿锄'), text_item('花费工资：5'),
            text_item('花费工资：50'), text_item('等级限制：70')]))

    def test_conflicting_detail_levels_do_not_authorize_checkout(self):
        self.assertFalse(middle_pickaxe_detail([
            text_item('中级精钢矿锄'), text_item('花费工资：5'),
            text_item('等级限制：70'), text_item('等级限制：110')]))

    def test_receipt_matches_user_success_dialog(self):
        items = [text_item('兑换成功，获得道具中级精钢矿锄'),
                 text_item('1个，失去工资5')]
        self.assertTrue(purchase_receipt(items))

    def test_wrong_receipt_item_quantity_or_cost_is_not_success(self):
        for name, quantity, cost in [('高级精钢矿锄', 1, 5),
                                    ('中级精钢矿锄', 2, 5),
                                    ('中级精钢矿锄', 10, 5),
                                    ('中级精钢矿锄', 11, 5),
                                    ('中级精钢矿锄', 1, 10),
                                    ('中级精钢矿锄', 1, 50),
                                    ('中级精钢矿锄', 1, 500)]:
            with self.subTest(name=name, quantity=quantity, cost=cost):
                self.assertFalse(purchase_receipt([text_item(
                    f'兑换成功，获得道具{name}{quantity}个，失去工资{cost}')]))

    def test_receipt_requires_explicit_success_and_cost(self):
        for text in ('中级精钢矿锄1个，失去工资5',
                     '兑换成功，获得道具中级精钢矿锄1个',
                     '兑换失败，获得道具中级精钢矿锄1个，失去工资5',
                     '兑换成功，获得道具中级精钢矿锄，失去工资5'):
            with self.subTest(text=text):
                self.assertFalse(purchase_receipt([text_item(text)]))

    def test_conflicting_receipts_do_not_confirm_a_new_purchase(self):
        correct = text_item('兑换成功，获得道具中级精钢矿锄1个，失去工资5')
        for conflicting in ('兑换成功，获得道具中级精钢矿锄2个，失去工资5',
                            '兑换成功，获得道具中级精钢矿锄1个，失去工资50'):
            with self.subTest(conflicting=conflicting):
                self.assertFalse(purchase_receipt([correct, text_item(conflicting)]))


if __name__ == '__main__':
    unittest.main()
