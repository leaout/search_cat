"""Build36 wage-shop calibration from user screenshots (native UI scale).

Coordinates are relative to recognized panel text, never desktop coordinates.
Only translation is supported; inconsistent/scaled anchors fail closed.
"""
import re
import hashlib
from statistics import median


SHOP_POINTS = {
    'shop_tab': (88, 49), 'consumables': (2, 108), 'experience': (7, 130),
    'middle_pickaxe': (305, 260), 'exchange': (635, 300), 'close': (693, 12),
}
SHOP_REGIONS = {
    'wages': (405, 30, 175, 32), 'detail': (360, 272, 330, 140),
    'receipt': (180, 212, 240, 168),
}


def purchase_session_key(identity: str) -> str:
    identity = str(identity).strip()
    if not identity:
        raise ValueError('自动购买必须填写角色唯一标识')
    return 'mining-role-' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]


def compact(text: str) -> str:
    return re.sub(r'\s+', '', str(text or '')).replace('：', ':')


def panel_anchor(items: list[dict], panel: str, center_of) -> tuple[int, int] | None:
    offsets = ({'游戏活动展示': (0, 0), '今日福利': (-98, 39), '活跃度': (243, 39)}
               if panel == 'activity' else
               {'工资商店': (0, 0), '商店物品': (88, 49), '推荐': (0, 49),
                '消耗品': (2, 108), '经验&抗性': (7, 130)})
    candidates = []
    for item in items:
        label = compact(item.get('text', ''))
        point = center_of(item)
        if point is None:
            continue
        for text, offset in offsets.items():
            if label == text or (text == '工资商店' and label in ('￥工资商店', '¥工资商店')):
                candidates.append((text, point[0] - offset[0], point[1] - offset[1]))
    # Each candidate needs a second, different label agreeing on position.
    fits = []
    for label, x, y in candidates:
        group = [entry for entry in candidates if abs(entry[1] - x) <= 8 and abs(entry[2] - y) <= 8]
        if len({entry[0] for entry in group}) >= 2:
            fits.append(group)
    if not fits:
        return None
    best = max(fits, key=lambda group: len({entry[0] for entry in group}))
    return round(median([entry[1] for entry in best])), round(median([entry[2] for entry in best]))


def shop_point(anchor: tuple[int, int], name: str) -> tuple[int, int]:
    dx, dy = SHOP_POINTS[name]
    return anchor[0] + dx, anchor[1] + dy


def shop_region(anchor: tuple[int, int], name: str) -> tuple[int, int, int, int]:
    dx, dy, width, height = SHOP_REGIONS[name]
    return anchor[0] + dx, anchor[1] + dy, width, height


def wage_balance(items: list[dict]) -> int | None:
    # Paddle commonly separates the heading, digits, and final "点" into
    # three OCR items in this narrow crop. Preserve all detected balances.
    text = ''.join(compact(item.get('text', '')) for item in items)
    values = {int(value) for value in re.findall(r'我的工资:?(\d+)点', text)}
    return next(iter(values)) if len(values) == 1 else None


def middle_pickaxe_detail(items: list[dict]) -> bool:
    # Preserve OCR line boundaries so "等级限制:70" followed by "70-109"
    # cannot become the invalid value "7070".
    text = ';'.join(compact(item.get('text', '')) for item in items)
    costs = {int(value) for value in re.findall(r'花费工资:(\d+)', text)}
    levels = {int(value) for value in re.findall(r'等级限制:(\d+)', text)}
    return ('中级精钢矿锄' in text and '高级精钢矿锄' not in text
            and costs == {5} and levels == {70})


def purchase_receipt(items: list[dict]) -> bool:
    text = ''.join(compact(item.get('text', '')) for item in items)
    quantities = {int(value) for value in re.findall(r'矿锄(\d+)个', text)}
    costs = {int(value) for value in re.findall(r'失去工资(\d+)', text)}
    return ('兑换成功' in text and '中级精钢矿锄' in text and '高级精钢矿锄' not in text
            and quantities == {1} and costs == {5})


def package_use_pending(items: list[dict]) -> bool:
    """Identify the boxed-item use warning, never authorize its confirmation."""
    text = ''.join(compact(item.get('text', '')) for item in items)
    risks = ('背包空间', '奖励堆叠', '邮箱发放', '无法获取', '多余的装备', '多余的炫装')
    hits = sum(keyword in text for keyword in risks)
    labels = {compact(item.get('text', '')) for item in items}
    return (hits >= 1 and '确定要使用' in text) or (hits >= 2 and {'确定', '取消'} <= labels)
