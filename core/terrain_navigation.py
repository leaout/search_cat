"""Experimental platform graph. Geometry is evidence, movement limits are calibration inputs."""
import heapq
import math


def closest_segment_points(a, b, c, d):
    """Closest points on two closed 2-D segments, including intersections."""
    def project(p, u, v):
        delta = (v[0] - u[0], v[1] - u[1])
        length = delta[0] ** 2 + delta[1] ** 2
        t = max(0, min(1, sum((p[k] - u[k]) * delta[k] for k in (0, 1)) / length)) if length else 0
        return tuple(u[k] + t * delta[k] for k in (0, 1))

    candidates = [(p, project(p, c, d)) for p in (a, b)]
    candidates += [(project(p, a, b), p) for p in (c, d)]
    r, s = (b[0]-a[0], b[1]-a[1]), (d[0]-c[0], d[1]-c[1])
    cross = r[0]*s[1] - r[1]*s[0]
    if abs(cross) > 1e-9:
        q = (c[0]-a[0], c[1]-a[1])
        t = (q[0]*s[1] - q[1]*s[0]) / cross
        u = (q[0]*r[1] - q[1]*r[0]) / cross
        if 0 <= t <= 1 and 0 <= u <= 1:
            p = (a[0]+t*r[0], a[1]+t*r[1])
            return p, p
    return min(candidates, key=lambda pair: math.dist(*pair))


def plan_route(records, start, target, scale=100, jump_x=180, jump_up=120,
               drop=250, allow_climb=False, snap=100):
    """Return actions in minimap units; never use the legacy NPC coordinate catalog."""
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('坐标倍率必须大于零')
    platforms = [r for r in records if r[1] in (2, 4) and r[3] != r[5]]
    nodes, owners, edges = [], [], []
    node_ids = {}

    def add(point, owner):
        key = (owner, round(point[0], 6), round(point[1], 6))
        if key in node_ids:
            return node_ids[key]
        nodes.append(tuple(point)); owners.append(owner); edges.append([])
        node_ids[key] = len(nodes) - 1
        return len(nodes) - 1

    def attach(point):
        candidates = []
        for r in platforms:
            x = max(min(r[3], r[5]), min(max(r[3], r[5]), point[0]))
            y = r[4] + (x - r[3]) * (r[6] - r[4]) / (r[5] - r[3])
            candidates.append((math.dist(point, (x, y)), r[0], (x, y)))
        if not candidates:
            raise ValueError('没有可用平台')
        distance, owner, position = min(candidates)
        if distance > snap:
            raise ValueError(f'标记距最近平台 {distance:.0f}，超出吸附范围 {snap}；请校准位置和倍率')
        return add(position, owner)

    for r in platforms:
        add(r[3:5], r[0]); add(r[5:7], r[0])
    origin, goal = attach(start), attach(target)
    climbs = []
    if allow_climb:
        for r in records:
            if r[1] == 8:
                try:
                    a, b = attach(r[3:5]), attach(r[5:7])
                except ValueError:
                    continue
                climbs.append((a, b))
    # A slope can only transfer at its ends. Perpendicular projections onto
    # a slope created shortcuts through the middle of stair flights.
    transfers = set()
    for index, first in enumerate(platforms):
        for second in platforms[index + 1:]:
            a, b = transfer_points(first, second)
            if abs(a[0]-b[0]) <= jump_x and abs(a[1]-b[1]) <= max(jump_up, drop):
                i, j = add(a, first[0]), add(b, second[0])
                transfers.update(((i, j), (j, i)))
    for i, a in enumerate(nodes):
        for j, b in enumerate(nodes):
            if i == j:
                continue
            dx, dy = abs(b[0] - a[0]), b[1] - a[1]
            action = None
            if owners[i] == owners[j] or ((i, j) in transfers and math.dist(a, b) < 1):
                action = 'walk'
            elif (i, j) in transfers and dx <= jump_x and -jump_up <= dy <= drop:
                action = 'drop' if dy > jump_up else 'jump'
            if action:
                # Use geometric shortest-path; the executor decides whether a
                # transfer starts with a standing or directional jump.
                edges[i].append((j, action, math.dist(a, b)))
    for a, b in climbs:
        edges[a].append((b, 'climb', math.dist(nodes[a], nodes[b])))
        edges[b].append((a, 'climb', math.dist(nodes[a], nodes[b])))
    queue, costs, previous = [(0, origin)], {origin: 0}, {}
    while queue:
        cost, i = heapq.heappop(queue)
        if cost != costs[i]:
            continue
        if i == goal:
            break
        for j, action, weight in edges[i]:
            total = cost + weight
            if total < costs.get(j, float('inf')):
                costs[j] = total; previous[j] = (i, action)
                heapq.heappush(queue, (total, j))
    if goal not in costs:
        raise ValueError('当前跳跃范围内没有连通路线；请调整实测能力或标记位置')
    steps, node = [], goal
    while node != origin:
        parent, action = previous[node]
        if math.dist(nodes[parent], nodes[node]) > 0.1:
            steps.append({'action': action,
                          'from': [v / scale for v in nodes[parent]],
                          'to': [v / scale for v in nodes[node]],
                          'segment': owners[node]})
        node = parent
    return {'map': '成都.子城', 'scale': scale, 'start': [v / scale for v in nodes[origin]],
            'target': [v / scale for v in nodes[goal]], 'steps': list(reversed(steps)),
            'experimental': True}


def transfer_points(first, second):
    """Use slope ends and horizontal projections, symmetrically in both directions."""
    a, b, c, d = first[3:5], first[5:7], second[3:5], second[5:7]
    first_slope = a[1] != b[1]
    second_slope = c[1] != d[1]
    if first_slope and second_slope:
        return min(((p, q) for p in (a, b) for q in (c, d)),
                   key=lambda pair: math.dist(*pair))
    if first_slope:
        return min(((p, (max(min(c[0], d[0]), min(max(c[0], d[0]), p[0])), c[1]))
                    for p in (a, b)), key=lambda pair: math.dist(*pair))
    if second_slope:
        q, p = transfer_points(second, first)
        return p, q
    return closest_segment_points(a, b, c, d)
