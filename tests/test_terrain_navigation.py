import unittest

from core.terrain_navigation import plan_route, transfer_points


class TerrainPlanTests(unittest.TestCase):
    def test_slope_to_slope_uses_endpoints_in_both_directions(self):
        first = (1, 4, 0, 100, 200, 300, 400, 0)
        second = (2, 4, 0, 80, 170, 300, 60, 0)
        for a, b in ((first, second), (second, first)):
            p, q = transfer_points(a, b)
            self.assertIn(p, (a[3:5], a[5:7]))
            self.assertIn(q, (b[3:5], b[5:7]))
        self.assertEqual(transfer_points(first, second), ((100, 200), (80, 170)))

    def test_horizontal_slope_never_projects_onto_slope_middle(self):
        floor = (1, 2, 0, 140, 280, 400, 280, 0)
        slope = (2, 4, 0, 100, 300, 300, 100, 0)
        p, q = transfer_points(floor, slope)
        self.assertIn(q, (slope[3:5], slope[5:7]))
        self.assertEqual(transfer_points(slope, floor), (q, p))

    def test_connected_slopes_walk_without_jump(self):
        rows = [(1, 4, 0, 0, 300, 100, 200, 0), (2, 4, 0, 100, 200, 200, 250, 0)]
        plan = plan_route(rows, (0, 300), (200, 250))
        self.assertTrue(all(s['action'] == 'walk' for s in plan['steps']))

    def test_jump_waits_for_closest_floor_slope_point(self):
        rows = [(1, 2, 0, 0, 500, 2000, 500, 0),
                (2, 4, 0, 700, 450, 1000, 300, 0)]
        plan = plan_route(rows, (1400, 500), (1000, 300), jump_x=500)
        self.assertEqual(plan['steps'][0]['action'], 'walk')
        self.assertEqual(plan['steps'][0]['to'], [7, 5])
        jump = next(s for s in plan['steps'] if s['action'] == 'jump')
        self.assertEqual(jump['from'], [7, 5])
        self.assertEqual(jump['to'], [7, 4.5])

    def test_takeoff_from_middle_of_long_floor(self):
        rows = [(1, 2, 0, 0, 500, 2000, 500, 0),
                (2, 4, 0, 700, 450, 1000, 300, 0)]
        plan = plan_route(rows, (1500, 500), (1000, 300), jump_x=180, jump_up=120)
        jumps = [s for s in plan['steps'] if s['action'] == 'jump']
        self.assertTrue(jumps)
        self.assertTrue(all(0 < s['from'][0] < 20 for s in jumps))
        self.assertLess(sum(abs(s['to'][0] - s['from'][0]) for s in plan['steps']), 12)

    def test_same_platform_walk(self):
        plan = plan_route([(1, 2, 0, 0, 100, 1000, 100, 0)], (100, 100), (700, 100))
        self.assertEqual([s['action'] for s in plan['steps']], ['walk'])
        self.assertEqual(plan['target'], [7, 1])

    def test_gap_requires_jump(self):
        rows = [(1, 2, 0, 0, 100, 200, 100, 0), (2, 2, 0, 300, 50, 500, 50, 0)]
        plan = plan_route(rows, (100, 100), (400, 50), jump_x=110)
        self.assertIn('jump', [s['action'] for s in plan['steps']])
        with self.assertRaises(ValueError):
            plan_route(rows, (100, 100), (400, 50), jump_x=50)

    def test_vertical_line_requires_explicit_climb(self):
        rows = [(1, 2, 0, 0, 500, 200, 500, 0), (2, 2, 0, 0, 100, 200, 100, 0),
                (3, 8, 0, 100, 500, 100, 100, 0)]
        with self.assertRaises(ValueError):
            plan_route(rows, (100, 500), (100, 100))
        plan = plan_route(rows, (100, 500), (100, 100), allow_climb=True)
        self.assertIn('climb', [s['action'] for s in plan['steps']])

    def test_unmapped_point_rejected(self):
        with self.assertRaises(ValueError):
            plan_route([(1, 2, 0, 0, 100, 1000, 100, 0)], (100, 500), (700, 100))
