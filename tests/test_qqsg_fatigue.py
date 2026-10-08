"""Pure OCR-text checks for gathering fatigue; no capture or game input."""

import unittest

from plugin_platform.qqsg_fatigue import (fatigue_hover_points, fatigue_tooltip_region,
                                        parse_gathering_fatigue, status_panel_anchor,
                                        status_tabs_region)


def text_item(text: str) -> dict:
    return {'text': text}


def status_items(origin=(430, 238), include_stats=False) -> list[dict]:
    offsets = [('角色信息', (69, 68)), ('角色抗性', (152, 70))]
    if include_stats:
        offsets += [('恶行', (173, 209)), ('声望', (173, 230))]
    return [{'text': label, 'center': [origin[0] + dx, origin[1] + dy]}
            for label, (dx, dy) in offsets]


class StatusPanelLocationTests(unittest.TestCase):
    def test_user_screenshot_tabs_locate_native_client_origin(self):
        self.assertEqual(status_panel_anchor(status_items()), (430, 238))

    def test_both_optional_stats_agree_with_screenshot(self):
        self.assertEqual(status_panel_anchor(status_items(include_stats=True)), (430, 238))

    def test_panel_can_be_translated_without_fixed_fullscreen_coordinates(self):
        for origin in ((0, 0), (32, 70), (612, 123), (900, 500)):
            with self.subTest(origin=origin):
                self.assertEqual(status_panel_anchor(status_items(origin)), origin)

    def test_resize_does_not_scale_native_offsets(self):
        anchor = status_panel_anchor(status_items((30, 40)))
        self.assertEqual(fatigue_hover_points(anchor)[0], (325, 251))
        self.assertEqual(fatigue_tooltip_region(anchor, 1280, 960), (135, 151, 430, 190))
        self.assertEqual(fatigue_tooltip_region(anchor, 1920, 1080), (135, 151, 430, 190))

    def test_scaled_tab_positions_do_not_authorize_native_pixel_points(self):
        items = [{'text': label, 'center': [430 + dx * 2, 238 + dy * 2]}
                 for label, (dx, dy) in [('角色信息', (69, 68)), ('角色抗性', (152, 70))]]
        self.assertIsNone(status_panel_anchor(items))

    def test_two_distinct_panels_are_ambiguous(self):
        self.assertIsNone(status_panel_anchor(status_items() + status_items((100, 80))))

    def test_far_duplicate_label_is_not_treated_as_same_panel(self):
        self.assertIsNone(status_panel_anchor(status_items() + [
            {'text': '角色信息', 'center': [200, 170]}]))

    def test_same_position_duplicate_and_whitespace_are_safe(self):
        items = status_items()
        items += [{'text': ' 角色 信息 ', 'center': items[0]['center']}]
        self.assertEqual(status_panel_anchor(items), (430, 238))

    def test_each_isolated_tab_is_rejected(self):
        for item in status_items():
            with self.subTest(label=item['text']):
                self.assertIsNone(status_panel_anchor([item]))

    def test_status_title_and_stats_cannot_replace_both_tabs(self):
        self.assertIsNone(status_panel_anchor([
            {'text': '状态', 'center': [500, 260]},
            *status_items(include_stats=True)[2:]]))

    def test_misaligned_tabs_are_rejected(self):
        items = status_items()
        items[1]['center'][1] += 9
        self.assertIsNone(status_panel_anchor(items))

    def test_small_ocr_jitter_is_tolerated_without_scaling(self):
        items = status_items()
        items[1]['center'][0] += 4
        items[1]['center'][1] -= 2
        self.assertEqual(status_panel_anchor(items), (432, 237))

    def test_optional_stat_on_another_panel_is_rejected(self):
        for label in ('恶行', '声望'):
            with self.subTest(label=label):
                self.assertIsNone(status_panel_anchor(status_items() + [
                    {'text': label, 'center': [200, 100]}]))

    def test_negative_origin_or_coordinate_is_rejected(self):
        for origin in ((-1, 0), (0, -1), (-100, 0)):
            with self.subTest(origin=origin):
                self.assertIsNone(status_panel_anchor(status_items(origin)))

    def test_invalid_centers_are_rejected(self):
        for center in (None, [], [True, 306], ['499', 306], [float('nan'), 306],
                       [499, float('inf')], [-1, 306]):
            with self.subTest(center=center):
                items = status_items()
                items[0]['center'] = center
                self.assertIsNone(status_panel_anchor(items))

    def test_four_point_ocr_boxes_are_supported(self):
        items = status_items()
        for item in items:
            x, y = item.pop('center')
            item['box'] = [[x - 20, y - 8], [x + 20, y - 8],
                           [x + 20, y + 8], [x - 20, y + 8]]
        self.assertEqual(status_panel_anchor(items), (430, 238))

    def test_malformed_or_negative_box_corners_are_rejected(self):
        for box in ([], [[499, 306]], [[-1, 300], [520, 300], [520, 310], [480, 310]],
                    [[480, 300], [520, 300], [520, 310], ['480', 310]]):
            with self.subTest(box=box):
                items = status_items()
                items[0].pop('center')
                items[0]['box'] = box
                self.assertIsNone(status_panel_anchor(items))

    def test_unrelated_text_does_not_change_panel_origin(self):
        self.assertEqual(status_panel_anchor(status_items() + [
            {'text': '采集疲劳度334/2520', 'center': [834, 409]},
            {'text': '状态', 'center': [496, 264]}, {}]), (430, 238))

    def test_empty_or_missing_geometry_has_no_anchor(self):
        self.assertIsNone(status_panel_anchor([]))
        self.assertIsNone(status_panel_anchor([text_item('角色信息'), text_item('角色抗性')]))


class FatigueAutomaticRegionTests(unittest.TestCase):
    def test_hover_has_only_three_bounded_native_pixel_candidates(self):
        self.assertEqual(fatigue_hover_points((430, 238)),
                         [(725, 449), (720, 449), (730, 449)])

    def test_tooltip_roi_covers_both_sides_of_icon(self):
        self.assertEqual(fatigue_tooltip_region((430, 238), 1280, 960), (535, 349, 430, 190))

    def test_tabs_roi_is_small_and_separate_from_character_stats(self):
        self.assertEqual(status_tabs_region((430, 238), 1280, 960), (454, 285, 185, 44))

    def test_tooltip_is_clipped_to_client_right_and_bottom(self):
        self.assertEqual(fatigue_tooltip_region((400, 300), 700, 500), (505, 411, 195, 89))

    def test_tabs_are_clipped_to_client_right_and_bottom(self):
        self.assertEqual(status_tabs_region((400, 300), 550, 370), (424, 347, 126, 23))

    def test_completely_offscreen_rois_are_rejected(self):
        self.assertIsNone(fatigue_tooltip_region((430, 238), 500, 300))
        self.assertIsNone(status_tabs_region((430, 238), 450, 280))

    def test_invalid_anchors_do_not_create_hover_or_capture(self):
        for anchor in ((-1, 0), (0, -1), (False, 0), (1.5, 2), (), None, '430,238'):
            with self.subTest(anchor=anchor):
                self.assertEqual(fatigue_hover_points(anchor), [])
                self.assertIsNone(fatigue_tooltip_region(anchor, 1280, 960))
                self.assertIsNone(status_tabs_region(anchor, 1280, 960))

    def test_invalid_client_dimensions_do_not_create_capture(self):
        for width, height in ((0, 960), (1280, 0), (-1, 960), (True, 960),
                              (1280, 960.0), ('1280', 960)):
            with self.subTest(width=width, height=height):
                self.assertIsNone(fatigue_tooltip_region((430, 238), width, height))
                self.assertIsNone(status_tabs_region((430, 238), width, height))


class GatheringFatigueTests(unittest.TestCase):
    def test_user_screenshot_reading_uses_actual_limit(self):
        self.assertEqual(parse_gathering_fatigue([text_item('采集疲劳度334/2520')]), (334, 2520))

    def test_zero_used_and_old_weekly_limit_are_valid(self):
        self.assertEqual(parse_gathering_fatigue([text_item('采集疲劳度0/2040')]), (0, 2040))

    def test_equal_used_and_limit_is_readable_as_exhausted(self):
        self.assertEqual(parse_gathering_fatigue([text_item('采集疲劳度2520/2520')]), (2520, 2520))

    def test_limit_is_not_hard_coded(self):
        for used, limit in ((1, 360), (500, 1800), (2345, 3000), (0, 1)):
            with self.subTest(used=used, limit=limit):
                self.assertEqual(parse_gathering_fatigue([
                    text_item(f'采集疲劳度{used}/{limit}')]), (used, limit))

    def test_ocr_spaces_full_width_slash_and_colon_are_normalized(self):
        for text in ('采集疲劳度 ： 334 ／ 2520', ' 采 集 疲 劳 度: 334 / 2520\n',
                     '采集疲劳度：0／2040'):
            with self.subTest(text=text):
                expected = (0, 2040) if '2040' in text else (334, 2520)
                self.assertEqual(parse_gathering_fatigue([text_item(text)]), expected)

    def test_label_and_fraction_in_adjacent_items_are_recognized(self):
        self.assertEqual(parse_gathering_fatigue([
            text_item('采集疲劳度'), text_item('334/2520')]), (334, 2520))
        self.assertEqual(parse_gathering_fatigue([
            text_item('采集疲劳度：'), text_item('334'), text_item('/'),
            text_item('2520')]), (334, 2520))

    def test_duplicate_identical_reading_is_not_a_conflict(self):
        self.assertEqual(parse_gathering_fatigue([
            text_item('采集疲劳度334/2520'), text_item('采集疲劳度：334／2520')]), (334, 2520))

    def test_conflicting_used_or_limit_returns_unknown(self):
        for other in ('采集疲劳度335/2520', '采集疲劳度334/2040'):
            with self.subTest(other=other):
                self.assertIsNone(parse_gathering_fatigue([
                    text_item('采集疲劳度334/2520'), text_item(other)]))

    def test_conflicting_split_readings_are_not_concatenated_into_one_value(self):
        self.assertIsNone(parse_gathering_fatigue([
            text_item('采集疲劳度'), text_item('334/2520'),
            text_item('采集疲劳度'), text_item('335/2520')]))

    def test_fraction_without_gathering_label_is_not_a_reading(self):
        for text in ('334/2520', '疲劳度334/2520', '采集次数334/2520',
                     '生命21785/21785', '体力2426/2426', '耐久334/360'):
            with self.subTest(text=text):
                self.assertIsNone(parse_gathering_fatigue([text_item(text)]))

    def test_label_without_its_own_value_does_not_use_health_or_durability(self):
        for text in ('生命21785/21785', '体力2426/2426', '耐久334/360'):
            with self.subTest(text=text):
                self.assertIsNone(parse_gathering_fatigue([
                    text_item('采集疲劳度'), text_item(text)]))

    def test_other_labeled_fractions_do_not_override_valid_fatigue(self):
        self.assertEqual(parse_gathering_fatigue([
            text_item('生命21785/21785'), text_item('体力2426/2426'),
            text_item('采集疲劳度334/2520'), text_item('耐久334/360')]), (334, 2520))

    def test_zero_denominator_used_over_limit_and_negative_values_are_rejected(self):
        for text in ('采集疲劳度0/0', '采集疲劳度334/0', '采集疲劳度2521/2520',
                     '采集疲劳度-1/2520', '采集疲劳度334/-2520', '采集疲劳度-1/-2520'):
            with self.subTest(text=text):
                self.assertIsNone(parse_gathering_fatigue([text_item(text)]))

    def test_incomplete_or_unreadable_value_is_unknown(self):
        for text in ('采集疲劳度', '采集疲劳度334/', '采集疲劳度/2520',
                     '采集疲劳度334', '采集疲劳度三百三十四/2520'):
            with self.subTest(text=text):
                self.assertIsNone(parse_gathering_fatigue([text_item(text)]))

    def test_empty_ocr_items_are_unknown(self):
        self.assertIsNone(parse_gathering_fatigue([]))
        self.assertIsNone(parse_gathering_fatigue([{}, {'text': ''}, {'text': None}]))


if __name__ == '__main__':
    unittest.main()
