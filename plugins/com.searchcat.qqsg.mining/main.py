"""QQ 三国 multi-window mining plugin.

Each bound game window gets its own worker process from the script platform. The
default flow switches to line 14, follows configured movement actions to the
mine, then patrols and presses G at each configured point. Travel is kept as
explicit data because different characters can start on different maps.
"""

from __future__ import annotations

import re
import time
import hashlib
import uuid
from typing import Any
from plugin_platform.line_grid import find_line_target, infer_server_menu_button
from plugin_platform.qqsg_code_navigation import MINING_MAPS, navigate_and_wait
from plugin_platform.qqsg_pickaxe_shop import (compact as shop_compact, panel_anchor, shop_point,
                                             shop_region, wage_balance, middle_pickaxe_detail,
                                             purchase_receipt, package_use_pending)


ORE_RESOURCE = "images/ore.png"
PICKAXE_RESOURCE = 'images/pickaxe.png'


class GatheringFatigueLimitReached(RuntimeError):
    """An observed gathering limit ends this run normally, not as a failure."""


def _ensure_gathering_fatigue(context) -> None:
    """Read F1 automatically; pause on unknown or unrestored UI, never old data."""
    if not context.config.get('fatigue_monitor_enabled', False):
        return
    if context.dry_run:
        context.log('模拟采集疲劳检查：F1 状态 → 自动定位悬停 → 读取 → 收起；不发送操作')
        return
    window = context.windows.current()
    key = re.sub(r'[^\w-]', '_', str(window.get('hwnd') or window.get('id') or 'current'))
    previous = None
    while True:
        if not context.windows.is_alive():
            raise RuntimeError('疲劳检查期间游戏窗口已关闭')
        # One host RPC owns the foreground input lock for the whole sequence.
        # Independent mouse/keyboard calls would let another window steal hover.
        result = context.windows.read_gathering_fatigue()
        value = result.get('reading') if isinstance(result, dict) else None
        reading = None
        if isinstance(result, dict) and result.get('ui_restored') is True \
                and isinstance(value, (list, tuple)) and len(value) == 2 \
                and all(type(number) is int for number in value) \
                and value[1] > 0 and 0 <= value[0] <= value[1]:
            reading = tuple(value)
        reason = str(result.get('reason', '')) if isinstance(result, dict) else '读取结果无效'
        state = 'unknown' if reading is None else ('exhausted' if reading[0] == reading[1] else 'ready')
        snapshot = (state, reading, reason if reading is None else '')
        if snapshot != previous:
            context.storage.write_json(f'mining/fatigue-{key}.json', {
                'state': state, 'used': reading[0] if reading else None,
                'limit': reading[1] if reading else None,
                'remaining': reading[1] - reading[0] if reading else None,
                'observed_at': time.time(), 'window': window, 'source': 'f1', 'detail': reason,
            })
            context.debug.watch('gathering_fatigue', {
                'state': state, 'reading': list(reading) if reading else None,
            })
            if reading:
                context.log(f'采集疲劳：{reading[0]}/{reading[1]}，剩余 {reading[1] - reading[0]}')
            else:
                context.log(f'F1 采集疲劳读取未完成，暂停移动、采集及补购；{reason or "等待复查"}', 'warning')
            previous = snapshot
        if state == 'exhausted':
            raise GatheringFatigueLimitReached('采集疲劳已达到当前上限')
        if state == 'ready':
            return
        context.sleep(max(1.0, float(context.config.get('fatigue_recheck_seconds', 5))))


def _pickaxe_purchase_path(context) -> str:
    """Use an explicit stable character identity, never a changing line title."""
    identity = str(context.config.get('pickaxe_character_id', '')).strip()
    if not identity:
        raise ValueError('购买前必须配置唯一角色标识，不能用窗口标题或句柄代替角色')
    key = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]
    return f'mining/purchases-{key}.json'


def _reserve_pickaxe_purchase(context, wage_balance: int) -> str:
    """Persist a single-item reservation BEFORE any future checkout click.

    Budget persists across process restarts;
    ambiguous transactions intentionally require manual reconciliation.
    """
    if context.dry_run:
        raise ValueError('模拟运行不创建真实购买记录')
    budget = int(context.config.get('pickaxe_wage_budget', 0))
    if budget < 5 or wage_balance < 5:
        raise ValueError('工资余额或允许预算不足 5，不购买')
    path = _pickaxe_purchase_path(context)
    ledger = context.storage.read_json(path, default={})
    if not isinstance(ledger, dict):
        raise ValueError('购买记录损坏，需人工核对')
    if ledger.get('pending'):
        raise ValueError('上次购买结果待确认，禁止再次扣款')
    if ledger.get('unfulfilled'):
        raise ValueError('已购买矿锄道具尚未确认使用和装备，禁止重复购买')
    spent = ledger.get('spent', 0)
    if type(spent) is not int or spent < 0 or spent + 5 > budget:
        raise ValueError('已达到工资预算或记录不合法，不购买')
    transaction_id = uuid.uuid4().hex
    ledger['pending'] = {'id': transaction_id, 'cost': 5, 'quantity': 1,
                         'item': '中级精钢矿锄', 'created_at': time.time()}
    ledger['spent'] = spent
    context.storage.write_json(path, ledger)
    return transaction_id


def _confirm_pickaxe_purchase(context, transaction_id: str, receipt_verified: bool) -> bool:
    """Clear a reservation only after the future checkout verifies receipt."""
    path = _pickaxe_purchase_path(context)
    ledger = context.storage.read_json(path, default={})
    if not isinstance(ledger, dict) or not isinstance(ledger.get('pending'), dict) \
            or ledger['pending'].get('id') != transaction_id:
        raise ValueError('购买流水不匹配，需人工核对')
    if not receipt_verified:
        context.log('购买到账未确认，保留待确认流水，禁止重复购买', 'warning')
        return False
    pending = ledger['pending']
    if pending.get('cost') != 5 or pending.get('quantity') != 1 \
            or pending.get('item') != '中级精钢矿锄' \
            or type(ledger.get('spent')) is not int or ledger['spent'] < 0:
        raise ValueError('购买记录金额或物品不合法，需人工核对')
    ledger['spent'] += pending['cost']
    ledger['last_confirmed'] = {**pending, 'confirmed_at': time.time()}
    # Purchase success creates a boxed consumable, not equipped mining gear.
    # Persist this separate checkpoint across restarts to block duplicate buys.
    ledger['unfulfilled'] = {**pending, 'stage': 'boxed', 'purchased_at': time.time()}
    ledger['pending'] = None
    context.storage.write_json(path, ledger)
    return True


def _finish_pickaxe_fulfillment(context, reading: tuple[int, int]) -> bool:
    """Finish replenishment only after a fresh positive equipped-durability read."""
    if context.dry_run or not isinstance(reading, tuple) or len(reading) != 2 \
            or type(reading[0]) is not int or type(reading[1]) is not int \
            or reading[1] != 360 or not 0 < reading[0] <= reading[1]:
        return False
    if not str(context.config.get('pickaxe_character_id', '')).strip():
        return False
    path = _pickaxe_purchase_path(context)
    ledger = context.storage.read_json(path, default={})
    if not isinstance(ledger, dict):
        raise ValueError('矿锄购买记录损坏，需人工核对')
    outstanding = ledger.get('unfulfilled')
    if not outstanding:
        return False
    if not isinstance(outstanding, dict) or outstanding.get('stage') != 'boxed' \
            or not isinstance(ledger.get('last_confirmed'), dict) \
            or outstanding.get('id') != ledger['last_confirmed'].get('id'):
        raise ValueError('矿锄待补充记录不匹配，需人工核对')
    ledger['last_fulfilled'] = {**outstanding, 'durability': list(reading), 'equipped_at': time.time()}
    ledger['unfulfilled'] = None
    context.storage.write_json(path, ledger)
    context.log('已重新读到装备矿锄的正耐久，完成本次补充记录')
    return True


def _shop_scan(context, region=None, preprocess='none', single_line=False, min_confidence=0.55) -> list[dict]:
    frame = context.capture.window(area='client', region=region)
    return context.ocr.recognize(frame, min_confidence=min_confidence,
                                 preprocess=preprocess, single_line=single_line) or []


def _shop_click(context, point: tuple[int, int]) -> None:
    context.mouse.click(*point, button='left', mode='foreground', coordinate_space='client')
    context.mouse.move(8, 8, coordinate_space='client')
    context.sleep(0.20)


def _shop_panel(context, panel: str) -> tuple[int, int]:
    for _ in range(3):
        items = _shop_scan(context)
        anchor = panel_anchor(items, panel, _item_center)
        if anchor is not None:
            return anchor
        context.sleep(0.25)
    raise RuntimeError(f'未确认{panel}面板位置：需至少两个一致锚点，当前布局可能不同')


def _try_buy_middle_pickaxe(context) -> bool:
    """Execute screenshot-calibrated single-item checkout, never blind retries."""
    if context.dry_run:
        context.log('模拟购买中级矿锄：活动 I → 兑换 → 工资商店；不消费工资')
        return False
    _ensure_gathering_fatigue(context)
    # Fail before input for disabled/ambiguous budgets or incomplete equipment.
    path = _pickaxe_purchase_path(context)
    ledger = context.storage.read_json(path, default={})
    if not isinstance(ledger, dict) or ledger.get('pending'):
        raise ValueError('购买记录未知或上次交易待确认，禁止自动购买')
    if ledger.get('unfulfilled'):
        raise ValueError('已有已购买的矿锄道具待使用/装备，禁止再次扣工资')
    if int(context.config.get('pickaxe_wage_budget', 0)) < 5:
        raise ValueError('未设置至少 5 工资的购买预算')
    if type(ledger.get('spent', 0)) is not int or ledger.get('spent', 0) < 0 \
            or ledger.get('spent', 0) + 5 > int(context.config.get('pickaxe_wage_budget', 0)):
        raise ValueError('已达到工资预算或记录不合法')
    if str(context.config.get('pickaxe_expected_name', '中级精钢矿锄')) != '中级精钢矿锄':
        raise ValueError('截图购买流程仅支持中级精钢矿锄，不支持其他等级矿锄')
    if not context.config.get('pickaxe_auto_equip_enabled', False):
        raise ValueError('自动购买必须同时启用备用矿锄装备并完成配置')
    if str(context.config.get('pickaxe_equip_method', 'double_left')) not in ('double_left', 'right'):
        raise ValueError('矿锄装备方式未配置正确，禁止购买')
    if not all((context.config.get('pickaxe_inventory_key'), context.config.get('pickaxe_inventory_close_key'),
                _valid_region(context.config.get('pickaxe_inventory_region')),
                _valid_region(context.config.get('pickaxe_tooltip_region')))):
        raise ValueError('背包装备配置不完整，禁止购买后堆积矿锄')

    _activate(context)
    # Reuse an already-open shop/activity; I toggles the activity panel.
    initial_items = _shop_scan(context)
    anchor = panel_anchor(initial_items, 'shop', _item_center)
    if anchor is None:
        activity = panel_anchor(initial_items, 'activity', _item_center)
        if activity is None:
            context.keyboard.press('i', mode='foreground')
            context.mouse.move(8, 8, coordinate_space='client')
            context.sleep(0.25)
            activity = _shop_panel(context, 'activity')
        _shop_click(context, (activity[0] + 528, activity[1] + 149))
        anchor = _shop_panel(context, 'shop')
    context.log(f'工资商店锚点 {anchor}，使用截图校准的面板内相对位置')
    _shop_click(context, shop_point(anchor, 'shop_tab'))
    anchor = _shop_panel(context, 'shop')
    _shop_click(context, shop_point(anchor, 'consumables'))
    _shop_click(context, shop_point(anchor, 'experience'))
    # Move off icons before checking the panel and selecting the calibrated cell.
    anchor = _shop_panel(context, 'shop')
    balance = wage_balance(_shop_scan(context, shop_region(anchor, 'wages'), preprocess='task_scale'))
    if balance is None or balance < 5:
        raise ValueError('工资余额无法确认或不足 5，不兑换')
    _shop_click(context, shop_point(anchor, 'middle_pickaxe'))
    detail_region = shop_region(anchor, 'detail')
    if not middle_pickaxe_detail(_shop_scan(context, detail_region)):
        if not middle_pickaxe_detail(_shop_scan(context, detail_region, preprocess='task_scale')):
            raise RuntimeError('商品名称/价格5/等级70校验失败，不点击工资兑换')
    _shop_click(context, shop_point(anchor, 'exchange'))
    quantity_items = _shop_scan(context)
    headings = [item for item in quantity_items
                if shop_compact(item.get('text', '')).startswith('选择数量') and _item_center(item)]
    if len(headings) != 1:
        raise RuntimeError('未唯一定位选择数量窗口，不确认购买')
    quantity = _item_center(headings[0])
    if abs(quantity[0] - (anchor[0] + 560)) > 20 or abs(quantity[1] - (anchor[1] + 267)) > 20:
        raise RuntimeError('数量窗口位置与截图布局不符，不确认购买')
    _shop_click(context, (quantity[0] + 23, quantity[1] + 39))
    context.keyboard.hotkey('ctrl', 'a', mode='foreground')
    context.keyboard.type_text('1', mode='foreground')
    context.mouse.move(8, 8, coordinate_space='client')
    # The value is left-aligned: the supplied screenshot places "1" left of
    # the quantity-heading center. Include the entire input, not its right half.
    numbers = _shop_scan(context, (quantity[0] - 25, quantity[1] + 28, 100, 23),
                         single_line=True, min_confidence=0.35)
    if [shop_compact(item.get('text', '')) for item in numbers] != ['1']:
        raise RuntimeError('购买数量未确认是 1，不点击确定')
    # Verify a second, tighter crop too; the wider crop above must still be
    # exactly "1", so multi-digit quantities cannot pass via truncation alone.
    number_check = _shop_scan(context, (quantity[0] - 22, quantity[1] + 31, 35, 17),
                              single_line=True, min_confidence=0.50)
    if [shop_compact(item.get('text', '')) for item in number_check] != ['1']:
        raise RuntimeError('数量二次核对未通过，不点击确定')
    previous_receipt = _shop_scan(context, shop_region(anchor, 'receipt'))
    if any('兑换成功' in shop_compact(item.get('text', '')) for item in previous_receipt):
        raise RuntimeError('提交前已有兑换成功提示，无法确认新交易，不重复购买')
    transaction_id = _reserve_pickaxe_purchase(context, balance)
    context.log('已确认中级矿锄 1 个、5 工资，提交兑换（不自动重复提交）')
    _shop_click(context, (quantity[0] + 127, quantity[1] + 39))
    # Receipt is cropped to the dialog so old chat messages cannot prove a new purchase.
    receipt = False
    after = None
    for _ in range(3):
        receipt = purchase_receipt(_shop_scan(context, shop_region(anchor, 'receipt'), preprocess='task_scale'))
        after = wage_balance(_shop_scan(context, shop_region(anchor, 'wages'), preprocess='task_scale'))
        if receipt and after == balance - 5:
            break
        context.sleep(0.3)
    verified = receipt and after == balance - 5
    _confirm_pickaxe_purchase(context, transaction_id, verified)
    if not verified:
        context.log('兑换结果未知，已禁止重复扣款，请人工核对背包和工资', 'warning')
        return False
    _shop_click(context, (anchor[0] + 307, anchor[1] + 333))
    _shop_click(context, shop_point(anchor, 'close'))
    context.log('已确认兑换成功且工资减少 5；获得的是道具包，使用和装备尚待确认')
    _try_equip_spare_pickaxe(context)
    return True


def _try_equip_spare_pickaxe(context) -> bool:
    """Try using a verified item once; boxed-item warnings require manual handling."""
    config = context.config
    context._pickaxe_spare_state = 'unknown'
    inventory_region = _valid_region(config.get('pickaxe_inventory_region'))
    tooltip_region = _valid_region(config.get('pickaxe_tooltip_region'))
    open_key = str(config.get('pickaxe_inventory_key', '')).strip()
    close_key = str(config.get('pickaxe_inventory_close_key', '')).strip()
    if not inventory_region or not tooltip_region or not open_key or not close_key:
        context.log('自动换锄配置不完整：需要背包区域、提示区域及打开/关闭背包按键；转人工处理', 'warning')
        return False
    if context.dry_run:
        context.log('模拟备用矿锄装备，不发送按键或点击')
        return False
    expected = str(config.get('pickaxe_expected_name', '中级精钢矿锄'))
    _activate(context)
    if package_use_pending(_shop_scan(context)):
        context._pickaxe_spare_state = 'package_use_pending'
        context.log('矿锄道具使用确认尚未处理；装备栏空间未知，请人工确认并装备，不重复购买', 'warning')
        return False
    context.keyboard.press(open_key, mode='foreground')
    preserve_dialog = False
    try:
        context.sleep(0.3)
        expected_inventory = str(config.get('pickaxe_inventory_label', '物品')).strip()
        headers = _shop_scan(context)
        if package_use_pending(headers):
            preserve_dialog = True
            context._pickaxe_spare_state = 'package_use_pending'
            context.log('检测到道具使用确认，保留弹窗等待人工处理；不自动确认背包空间/奖励上限警告', 'warning')
            return False
        # The wage shop also has a "物品" heading. Its empty template search
        # must never be interpreted as proof that the backpack has no spare.
        other_panels = {'工资商店', '￥工资商店', '¥工资商店', '商店物品', '游戏活动展示'}
        if any(shop_compact(item.get('text', '')) in other_panels for item in headers):
            context.log('活动/工资商店仍在画面中，不能确认背包状态；不触发购买', 'warning')
            return False
        if not expected_inventory or not any(shop_compact(item.get('text', '')) == expected_inventory
                                             for item in headers):
            context.log('未确认背包已打开，不扫描空画面、不触发购买', 'warning')
            return False
        frame = context.capture.window(area='client', region=inventory_region)
        match = context.vision.find_image(frame, PICKAXE_RESOURCE, threshold=0.90, grayscale=False)
        point = _match_point(match, inventory_region)
        if point is None:
            context._pickaxe_spare_state = 'not_found_here'
            context.log('本页可见区域未找到矿锄，不能证明道具页和装备页都无备用；暂停等待人工处理', 'warning')
            return False
        context.mouse.move(*point, coordinate_space='client')
        context.sleep(0.6)
        tooltip = context.capture.window(area='client', region=tooltip_region)
        items = context.ocr.recognize(tooltip, min_confidence=0.60, preprocess='none') or []
        texts = [re.sub(r'\s+', '', str(item.get('text', ''))) for item in items]
        if not any(expected in text for text in texts):
            context.log('矿锄图标匹配后，名称提示未通过校验；不装备、不购买', 'warning')
            return False
        method = str(config.get('pickaxe_equip_method', 'double_left'))
        if method not in ('double_left', 'right'):
            raise ValueError('矿锄装备方式必须为 double_left 或 right')
        context.mouse.click(*point, button='right' if method == 'right' else 'left',
                            mode='foreground', coordinate_space='client')
        if method == 'double_left':
            context.sleep(0.08)
            context.mouse.click(*point, button='left', mode='foreground', coordinate_space='client')
        context.mouse.move(8, 8, coordinate_space='client')
        context.sleep(0.3)
        if package_use_pending(_shop_scan(context)):
            preserve_dialog = True
            context._pickaxe_spare_state = 'package_use_pending'
            context.log('已触发矿锄道具包的使用确认，还不是已装备；请人工处理后装备，脚本等待耐久恢复', 'warning')
            return False
        context.log('已尝试使用矿锄物品；开箱不等于装备，必须重新读到正耐久才恢复挖矿')
        context._pickaxe_spare_state = 'attempted'
        return True
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        context.log(f'自动换锄未完成：{error}；转人工处理', 'warning')
        return False
    finally:
        if not preserve_dialog:
            context.keyboard.press(close_key, mode='foreground')
            context.mouse.move(8, 8, coordinate_space='client')


def _parse_pickaxe_durability(items: list[dict]) -> tuple[int, int] | None:
    """Read only a valid fraction from the configured pickaxe status crop."""
    readings = set()
    for item in items:
        text = re.sub(r'\s+', '', str(item.get('text', ''))).replace('／', '/')
        for match in re.finditer(r'(?<!\d)(\d{1,3})/(\d{1,3})(?!\d)', text):
            current, maximum = map(int, match.groups())
            if maximum == 360 and 0 <= current <= maximum:
                readings.add((current, maximum))
    return next(iter(readings)) if len(readings) == 1 else None


def _ensure_pickaxe_ready(context) -> None:
    """Pause mining on depleted/unknown durability; allow manual replenishment."""
    if not context.config.get('pickaxe_monitor_enabled', False):
        return
    if context.dry_run:
        context.log('模拟矿锄耐久检查，不执行购买或装备')
        return
    region = _valid_region(context.config.get('pickaxe_region'))
    if region is None:
        raise ValueError('启用矿锄监控时必须配置 pickaxe_region，仅框选矿锄名称及耐久条')
    window = context.windows.current()
    window_key = str(window.get('hwnd') or window.get('id') or 'current')
    window_key = re.sub(r'[^\w-]', '_', window_key)
    last_state = None
    missing_streak = 0
    missing_threshold = max(2, int(context.config.get('pickaxe_missing_checks', 3)))
    equip_attempted = False
    purchase_attempted = False
    while True:
        _ensure_gathering_fatigue(context)
        frame = context.capture.window(area='client', region=region)
        items = context.ocr.recognize(frame, min_confidence=0.45, preprocess='none') or []
        reading = _parse_pickaxe_durability(items)
        # The equipped pickaxe vanishes when depleted: there may never be a
        # visible 0/360 frame. Empty OCR is only evidence of possible absence,
        # not authorization to spend wages or equip an arbitrary item.
        missing_streak = missing_streak + 1 if not items else 0
        state = 'ready' if reading and reading[0] > 0 else ('depleted' if reading else 'unknown')
        if not reading and missing_streak >= missing_threshold:
            state = 'missing_suspected'
        context.debug.watch('pickaxe_state', state)
        context.debug.watch('pickaxe_durability', list(reading) if reading else None)
        if state != last_state:
            context.storage.write_json(f'mining/pickaxe-{window_key}.json', {
                'state': state, 'durability': list(reading) if reading else None,
                'updated_at': time.time(), 'window': window,
                'missing_checks': missing_streak,
                'next_action': ('mine' if state == 'ready' else
                                'replenish_or_verify' if state in ('depleted', 'missing_suspected') else
                                'check_region_or_ocr'),
            })
            if state == 'missing_suspected':
                context.log(f'矿锄区域连续 {missing_streak} 次没有读到文字，疑似矿锄耗尽消失；'
                            '需要补充矿锄或人工确认遮挡/区域，未恢复耐久前不按 G。', 'warning')
            context.log(f'矿锄状态：{state}，耐久 {reading}；'
                        + ('继续挖矿' if state == 'ready' else '暂停移动和采集，等待人工装备矿锄或检查识别区域'),
                        'info' if state == 'ready' else 'warning')
            last_state = state
        if state == 'ready':
            _finish_pickaxe_fulfillment(context, reading)
            context._pickaxe_last_good = reading
            return
        if state in ('depleted', 'missing_suspected') and not equip_attempted \
                and context.config.get('pickaxe_auto_equip_enabled', False):
            equip_attempted = True
            _try_equip_spare_pickaxe(context)
            # Always recheck status after equipment before considering a purchase.
            context.sleep(max(1.0, float(context.config.get('pickaxe_recheck_seconds', 5))))
            continue
        if state in ('depleted', 'missing_suspected') and equip_attempted and not purchase_attempted \
                and context.config.get('pickaxe_auto_buy_enabled', False):
            purchase_attempted = True
            last_good = getattr(context, '_pickaxe_last_good', None)
            depletion_verified = state == 'depleted' or (
                isinstance(last_good, tuple) and 0 < last_good[0] <= 5 and state == 'missing_suspected')
            if not depletion_verified or getattr(context, '_pickaxe_spare_state', None) != 'absent':
                context.log('缺矿锄证据不足或背包检查未通过，只暂停等待，不自动消费工资', 'warning')
                context.sleep(max(1.0, float(context.config.get('pickaxe_recheck_seconds', 5))))
                continue
            try:
                _try_buy_middle_pickaxe(context)
            except (ValueError, RuntimeError) as error:
                context.log(f'自动补购未完成：{error}；停止自动消费，等待人工处理', 'warning')
        context.sleep(max(1.0, float(context.config.get('pickaxe_recheck_seconds', 5))))


def _valid_region(value: Any) -> tuple[int, int, int, int] | None:
    if value in (None, [], ()):
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("mining_region 必须是 [x, y, width, height]，或留空")
    x, y, width, height = (int(item) for item in value)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError("mining_region 的宽高必须大于 0，坐标不能为负数")
    return x, y, width, height


def _fallback_points(value: Any) -> list[tuple[int, int]]:
    if not isinstance(value, (list, tuple)):
        return []
    points = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            x, y = int(item[0]), int(item[1])
        except (TypeError, ValueError):
            continue
        if x >= 0 and y >= 0:
            points.append((x, y))
    return points


def _activate(context) -> None:
    if context.dry_run:
        return
    result = context.windows.activate()
    if isinstance(result, dict) and not result.get("active", True):
        raise RuntimeError("游戏窗口激活失败")


def _capture_and_find(context, region):
    frame = context.capture.window(area="client", region=region)
    match = context.vision.find_image(
        frame,
        ORE_RESOURCE,
        threshold=float(context.config.get("template_threshold", 0.82)),
        grayscale=True,
    )
    return frame, match


def _match_point(match, region) -> tuple[int, int] | None:
    if not getattr(match, "found", False):
        return None
    center = getattr(match, "center", None)
    if not isinstance(center, (list, tuple)) or len(center) < 2:
        return None
    offset_x, offset_y = (region[0], region[1]) if region else (0, 0)
    return int(center[0]) + offset_x, int(center[1]) + offset_y


def _click_mining_point(context, point, button, coordinate_space):
    _ensure_gathering_fatigue(context)
    x, y = point
    context.log(f"采集矿点：客户区 ({x}, {y})，鼠标 {button}")
    _activate(context)
    if context.dry_run:
        return
    context.mouse.click(
        x,
        y,
        button=button,
        mode="foreground",
        coordinate_space=coordinate_space,
    )
    # Moving the cursor away avoids covering the next template match.
    context.mouse.move(8, 8, coordinate_space="client")


def _wait(context, seconds: float) -> None:
    context.sleep(0.1 if context.dry_run else max(0.05, seconds))


def _compact(text: Any) -> str:
    return str(text or "").replace(" ", "").replace("\u3000", "").replace("：", ":")


def _item_center(item: dict[str, Any]) -> tuple[int, int] | None:
    center = item.get("center")
    if isinstance(center, (list, tuple)) and len(center) >= 2:
        return int(center[0]), int(center[1])
    box = item.get("box")
    if not isinstance(box, (list, tuple)):
        return None
    points = [point for point in box if isinstance(point, (list, tuple)) and len(point) >= 2]
    if not points:
        return None
    return (
        round(sum(float(point[0]) for point in points) / len(points)),
        round(sum(float(point[1]) for point in points) / len(points)),
    )


def _ocr_client(context, include_yellow: bool = False) -> list[dict[str, Any]]:
    """Read the client area for line-switch controls.

    The normal OCR pass is considerably faster than the yellow-mask pass.
    Scan once by default and only request the second pass when the target
    line is missing; this keeps ordinary line switching responsive while
    retaining a recovery path for outlined/even-column labels.
    """
    if not context.dry_run:
        context.mouse.move(8, 8, coordinate_space="client")
    frame = context.capture.window(area="client")
    base_items = list(context.ocr.recognize(frame, min_confidence=0.35, preprocess="none") or [])
    yellow_items = []
    if include_yellow:
        try:
            yellow_items = list(context.ocr.recognize(frame, min_confidence=0.30, preprocess="task_yellow") or [])
        except Exception:
            yellow_items = []
    merged = []
    seen = set()
    for item in base_items + yellow_items:
        text = _compact(item.get("text"))
        center = _item_center(item)
        key = (text, center)
        if not text or key in seen:
            continue
        seen.add(key)
        merged.append(item)
    for item in merged:
        item["_frame_width"] = int(frame.width)
        item["_frame_height"] = int(frame.height)
    if not merged:
        merged.append({'text': '', '_frame_width': int(frame.width), '_frame_height': int(frame.height)})
    return merged


def _find_server_button(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = []
    for item in items:
        text = _compact(item.get("text"))
        if not text or "客服" in text or _item_center(item) is None:
            continue
        score = 0
        if "服务器选线" in text:
            score = 4
        elif "服务器" in text and "选线" in text:
            score = 3
        elif text in {"选线", "服务器"}:
            score = 2
        if score:
            candidates.append((score, item))
    if candidates:
        return max(candidates, key=lambda value: value[0])[1]
    return infer_server_menu_button(items, _item_center)


def _build36_server_button(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Use the Build36 centered menu geometry when its text is unreadable."""
    width = next((int(item.get('_frame_width') or 0) for item in items if item.get('_frame_width')), 0)
    height = next((int(item.get('_frame_height') or 0) for item in items if item.get('_frame_height')), 0)
    if not 1100 <= width <= 1600 or not 800 <= height <= 1200:
        return None
    return {'text': '服务器选线（Build36 菜单位置）',
            'center': [round(width * 0.503), round(height * 0.535)], '_menu_fallback': True}


def _find_target_line(items: list[dict[str, Any]], target_line: int) -> dict[str, Any] | None:
    return find_line_target(items, target_line, _item_center)


def _available_lines(items: list[dict[str, Any]]) -> list[int]:
    found = set()
    pattern = re.compile(r"(?<!\d)(\d{1,2})\s*(?:线|号线|线路)")
    for item in items:
        text = _compact(item.get("text"))
        for match in pattern.finditer(text):
            found.add(int(match.group(1)))
        if text.isdigit() and 1 <= int(text) <= 99:
            found.add(int(text))
    return sorted(found)


def _find_confirm(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    preferred = ("确定", "确认", "进入游戏", "换线")
    candidates = []
    for item in items:
        text = _compact(item.get("text"))
        if not text or _item_center(item) is None:
            continue
        for rank, keyword in enumerate(preferred):
            if keyword in text:
                candidates.append((rank, len(text), item))
                break
    return min(candidates, key=lambda value: (value[0], value[1]))[2] if candidates else None


def _click_ocr_item(context, item: dict[str, Any]) -> None:
    center = _item_center(item)
    if center is None:
        raise RuntimeError("OCR 项目没有可点击坐标")
    context.mouse.click(center[0], center[1], mode="foreground", coordinate_space="client")
    if not context.dry_run:
        context.mouse.move(8, 8, coordinate_space="client")


def _switch_line_once(context, target_line: int) -> None:
    """Submit one line-switch attempt and verify the live window title."""
    context.log(f"准备切换到 {target_line} 线")
    _activate(context)
    if context.dry_run:
        context.log(f"模拟运行：打开选线界面并切换到 {target_line} 线")
        return
    current_title = str(context.windows.current().get('title', ''))
    if _line_from_title(current_title) == target_line:
        context.log(f'窗口标题已显示 {target_line} 线，跳过换线')
        return
    # QQSG renders a large hand cursor; move it away before every OCR pass so
    # it cannot cover a line label in the selector.
    context.mouse.move(8, 8, coordinate_space="client")
    first_items = _ocr_client(context)
    if len(_available_lines(first_items)) >= 3:
        context.log('检测到上次保留的选线列表，直接定位目标线路')
        line_items = first_items
    else:
        context.keyboard.press("esc", mode="foreground")
        _wait(context, float(context.config.get("line_switch_scan_wait", 0.35)))
        first_items = _ocr_client(context)
        if len(_available_lines(first_items)) >= 3:
            context.log('Esc 后进入选线列表，直接定位目标线路')
            line_items = first_items
        else:
            server_button = _find_server_button(first_items)
            if server_button is None:
                first_items = _ocr_client(context, include_yellow=True)
                server_button = _find_server_button(first_items)
            if server_button is None:
                server_button = _build36_server_button(first_items)
            if server_button is None:
                raise RuntimeError('无法定位“服务器选线”，且当前窗口不符合 Build36 菜单尺寸')
            if server_button.get('_menu_fallback'):
                context.log(f"菜单文字漏识别，按相邻按钮定位“服务器选线”：{server_button['center']}", 'warning')
            context.log(f"点击换线入口：{server_button.get('text', '') or '服务器选线'}")
            _click_ocr_item(context, server_button)
            _wait(context, float(context.config.get('line_switch_scan_wait', 0.35)))
            line_items = _ocr_client(context)
            if server_button.get('_menu_fallback') and len(_available_lines(line_items)) < 3:
                line_items = _ocr_client(context, include_yellow=True)
                if len(_available_lines(line_items)) < 3:
                    raise RuntimeError('点击换线入口后没有出现线路列表；请检查 Esc 是否打开了系统菜单')
    target = _find_target_line(line_items, target_line)
    if target is None:
        # One extra yellow-mask pass is only needed when the fast pass did not
        # produce enough anchors for a grid click.
        line_items = _ocr_client(context, include_yellow=True)
        target = _find_target_line(line_items, target_line)
    if target is None:
        available = _available_lines(line_items)
        visible = "、".join(f"{line}线" for line in available) if available else "无"
        samples = [f"{_compact(item.get('text'))}@{_item_center(item)}" for item in line_items
                   if any(f'{n}线' in _compact(item.get('text')) for n in (target_line - 1, target_line + 1))]
        raise RuntimeError(f"未能定位目标线路：{target_line}线；识别线路：{visible}；邻近 OCR：{samples[:8]}")
    if target.get("_grid_fallback"):
        context.log(f"未直接识别到 {target_line} 线，按选线网格定位点击", "warning")
    if target.get("_inferred_column"):
        context.log(f"整列漏识别，使用已验证的行间距和 Build36 面板布局定位：{target['center']}", "warning")
    context.log(f"点击目标线路：{target.get('text', '') or f'{target_line}线'}")
    confirm = _find_confirm(line_items)
    _click_ocr_item(context, target)
    _wait(context, 0.08)
    if confirm is None:
        confirm = _find_confirm(_ocr_client(context))
    if confirm is not None:
        context.log(f"点击确认：{confirm.get('text', '') or '确定'}")
        _click_ocr_item(context, confirm)
    else:
        context.log("未发现确认按钮，按回车提交换线", "warning")
        context.keyboard.press("enter", mode="foreground")
    context.log(f"已提交换线到 {target_line} 线")
    deadline = time.monotonic() + max(0.1, float(context.config.get('line_switch_wait', 3)))
    while True:
        live_title = str(context.windows.current().get('title', ''))
        if _line_from_title(live_title) == target_line or time.monotonic() >= deadline:
            break
        _wait(context, min(0.12, max(0.01, deadline - time.monotonic())))
    if _line_from_title(live_title) != target_line:
        raise RuntimeError(f'换线尚未成功，窗口标题仍是“{live_title}”')
    context.log(f'窗口标题确认已切换到 {target_line} 线')


def _line_from_title(title: str) -> int | None:
    """Read the final line number from a live QQSG window title."""
    matches = re.findall(r'(?<!\d)(\d{1,2})\s*线(?!\d)', title)
    return int(matches[-1]) if matches else None


def _dismiss_switch_failure(context) -> None:
    """Acknowledge a blocking game message before the next attempt."""
    items = _ocr_client(context)
    message = ''.join(_compact(item.get('text')) for item in items)
    failure_words = ('不能切换', '无法切换', '服务器已满', '线路已满', '人数已满', '换线失败')
    if not any(word in message for word in failure_words):
        return
    context.log(f'换线失败提示：{message[:100]}', 'warning')
    button = next((item for item in items
                   if ('确定' in _compact(item.get('text')) or '确认' in _compact(item.get('text')))
                   and _item_center(item) is not None), None)
    if button is not None:
        context.log('关闭换线失败提示，准备再次尝试')
        _click_ocr_item(context, button)
    else:
        context.log('未识别到失败提示的确定按钮，按回车关闭', 'warning')
        context.keyboard.press('enter', mode='foreground')
    _wait(context, 0.2)


def _switch_line(context, target_line: int) -> None:
    """Keep squeezing into the requested line until verified or attempts expire."""
    if context.dry_run:
        _switch_line_once(context, target_line)
        return
    max_attempts = int(context.config.get('line_switch_max_attempts', 30))
    if not 0 <= max_attempts <= 500:
        raise ValueError('line_switch_max_attempts 必须在 0 到 500 之间')
    retry_wait = max(0.1, float(context.config.get('line_switch_retry_wait', 0.3)))
    attempt = 0
    while max_attempts == 0 or attempt < max_attempts:
        attempt += 1
        context.log(f'换线尝试 {attempt}' + (f'/{max_attempts}' if max_attempts else '（持续尝试）'))
        try:
            _switch_line_once(context, target_line)
            return
        except RuntimeError as error:
            title = str(context.windows.current().get('title', ''))
            if _line_from_title(title) == target_line:
                context.log(f'窗口标题已确认 {target_line} 线，换线成功')
                return
            context.log(f'第 {attempt} 次未成功：{error}', 'warning')
            if max_attempts and attempt >= max_attempts:
                raise RuntimeError(f'{max_attempts} 次尝试后仍未切换到 {target_line} 线；最后状态：{error}') from error
            _dismiss_switch_failure(context)
            _wait(context, retry_wait)


def _normalize_actions(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} 必须是动作数组")
    actions = []
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict):
            raise ValueError(f"{name}[{index}] 必须是对象")
        direction = str(item.get("direction", "")).lower().strip()
        if direction and direction not in {"left", "right", "up", "down"}:
            raise ValueError(f"{name}[{index}].direction 只能是 left/right/up/down")
        seconds = float(item.get("seconds", item.get("duration", 0)))
        if seconds < 0 or seconds > 120:
            raise ValueError(f"{name}[{index}].seconds 必须在 0 到 120 之间")
        actions.append({
            "direction": direction,
            "seconds": seconds,
            "jump": bool(item.get("jump", False)),
            "g_count": max(0, int(item.get("g_count", 0))),
        })
    return actions


def _hold_direction(context, direction: str, seconds: float, jump: bool) -> None:
    if not direction or seconds <= 0:
        return
    _ensure_gathering_fatigue(context)
    _activate(context)
    if jump:
        context.keyboard.hold_combo(direction, "space", duration=min(3.0, max(0.03, seconds)), mode="foreground")
        remaining = seconds - min(3.0, max(0.03, seconds))
        if remaining > 0:
            _hold_direction(context, direction, remaining, False)
        return
    remaining = seconds
    while remaining > 0:
        _ensure_gathering_fatigue(context)
        pulse = min(2.5, remaining)
        if not context.dry_run:
            context.keyboard.key_down(direction, mode="foreground")
        try:
            _wait(context, pulse)
        finally:
            if not context.dry_run:
                context.keyboard.key_up(direction, mode="foreground")
        remaining -= pulse


def _press_g(context, count: int, interval: float) -> None:
    _activate(context)
    for _ in range(max(1, count)):
        _ensure_gathering_fatigue(context)
        if not context.dry_run:
            context.keyboard.press("g", mode="foreground")
        _wait(context, interval)


def _wait_for_refresh(context) -> None:
    mode = str(context.config.get("refresh_wait_mode", "next_hour"))
    if mode == "interval":
        seconds = max(60.0, float(context.config.get("refresh_interval", 3600)))
    else:
        now = time.time()
        seconds = 3600.0 - (now % 3600.0)
        if seconds < 5:
            seconds += 3600.0
    context.log(f"本轮巡逻完成，等待矿区刷新约 {round(seconds / 60, 1)} 分钟")
    if context.dry_run:
        context.log("模拟运行：跳过实际整点等待")
        return
    remaining = seconds
    while remaining > 0:
        _ensure_gathering_fatigue(context)
        if not context.windows.is_alive():
            raise RuntimeError("等待刷新期间游戏窗口已关闭")
        chunk = min(30.0, remaining)
        _wait(context, chunk)
        remaining -= chunk


def _run_patrol_g(context, actions: list[dict[str, Any]]) -> None:
    loops = max(0, int(context.config.get("patrol_loops", 0)))
    default_g = max(1, int(context.config.get("g_count", 1)))
    g_interval = max(0.1, float(context.config.get("g_interval", 0.8)))
    refresh_enabled = bool(context.config.get("refresh_wait_enabled", True))
    loop = 0
    while loops == 0 or loop < loops:
        loop += 1
        with context.step(f"矿区巡逻 {loop}"):
            for index, action in enumerate(actions, 1):
                _ensure_gathering_fatigue(context)
                _ensure_pickaxe_ready(context)
                direction = action["direction"]
                if direction:
                    context.log(
                        f"巡逻点 {index}/{len(actions)}：{direction} {action['seconds']:.2f}s"
                        + (" + 空格" if action["jump"] else "")
                    )
                    _hold_direction(context, direction, action["seconds"], action["jump"])
                count = action["g_count"] or default_g
                context.log(f"巡逻点 {index}：按 G {count} 次")
                _press_g(context, count, g_interval)
        if refresh_enabled and (loops == 0 or loop < loops):
            _wait_for_refresh(context)


def _run_template_loop(context, region) -> None:
    max_cycles = max(0, int(context.config.get("max_cycles", 30)))
    max_misses = max(1, int(context.config.get("max_misses", 3)))
    interval = max(0.05, float(context.config.get("mine_interval", 8)))
    button = str(context.config.get("mine_button", "right")).lower()
    coordinate_space = str(context.config.get("click_coordinate_space", "client")).lower()
    allow_fallback = bool(context.config.get("allow_coordinate_fallback", False))
    fallback_points = _fallback_points(context.config.get("fallback_points"))
    misses = 0
    cycles = 0
    point_index = 0
    while max_cycles == 0 or cycles < max_cycles:
        if not context.windows.is_alive():
            raise RuntimeError("绑定的游戏窗口已关闭")
        cycles += 1
        _ensure_gathering_fatigue(context)
        _ensure_pickaxe_ready(context)
        with context.step(f"挖矿 {cycles}"):
            point = None
            score = None
            try:
                _frame, match = _capture_and_find(context, region)
                score = float(getattr(match, "score", 0.0))
                point = _match_point(match, region)
            except (FileNotFoundError, ValueError, RuntimeError) as error:
                if not allow_fallback:
                    raise RuntimeError(f"矿点模板识别失败：{error}") from error
                context.log(f"模板识别失败，尝试备用坐标：{error}", "warning")
            if point is None and allow_fallback and fallback_points:
                point = fallback_points[point_index % len(fallback_points)]
                point_index += 1
            if point is None:
                misses += 1
                context.log(f"未识别到矿点（匹配分数 {score or 0:.3f}，连续 {misses}/{max_misses}）", "warning")
                if misses >= max_misses:
                    context.log("连续找不到矿点，安全结束当前窗口的挖矿")
                    return
                _wait(context, min(interval, 1.0))
                continue
            misses = 0
            context.log(f"矿点匹配分数：{score:.3f}" if score is not None else "使用备用采集点")
            _click_mining_point(context, point, button, coordinate_space)
            _wait(context, interval)


def on_load(context) -> None:
    context.log("QQ三国多窗口挖矿插件已加载")


def on_start(context) -> None:
    try:
        _run_mining(context)
    except GatheringFatigueLimitReached:
        context.log('采集疲劳达到上限，结束本次脚本；不再移动、采集或补购。已在进行的游戏采集需人工确认停止。')


def _travel_by_code(context) -> None:
    map_id = context.config.get('code_target_map_id', 907)
    if type(map_id) is not int or map_id not in MINING_MAPS:
        raise ValueError('代码寻路目标必须是江陵矿区走廊地图 ID：55/57/131/906/907/908')
    if not bool(context.config.get('code_navigation_only', False)) and map_id not in (906, 907, 908):
        raise ValueError('正常挖矿的代码目标只能是矿洞906/907/908；城镇/走廊目标仅限单独寻路调试')
    navigate_and_wait(
        context, map_id, context.config.get('code_target_x', 1000), context.config.get('code_target_y', 570),
        MINING_MAPS[map_id], start_map='江陵',
        timeout=float(context.config.get('code_navigation_timeout', 120)),
        interval=float(context.config.get('code_navigation_scan_interval', 0.7)),
    )


def _run_mining(context) -> None:
    config = context.config
    if bool(config.get('code_navigation_only', False)):
        with context.step('仅调试代码寻路（不换线、不采集、不购买）'):
            _travel_by_code(context)
        return
    if not bool(config.get('skip_travel', False)) and config.get('travel_mode', 'actions') == 'code' \
            and config.get('code_target_map_id', 907) not in (906, 907, 908):
        raise ValueError('正常挖矿的代码目标只能是矿洞906/907/908；请恢复矿区目标或开启仅调试寻路')
    if config.get('pickaxe_auto_buy_enabled', False) and not (
            config.get('pickaxe_monitor_enabled', False) and config.get('pickaxe_auto_equip_enabled', False)):
        raise ValueError('自动购买必须同时启用矿锄耐久监控和备用矿锄装备，请先完成配置')
    region = _valid_region(config.get("mining_region"))
    mode = str(config.get("mining_mode", "patrol_g")).lower()
    if mode not in {"patrol_g", "template"}:
        raise ValueError("mining_mode 只能是 patrol_g 或 template")
    use_templates = bool(config.get("use_templates", True))

    window = context.windows.current()
    title = str(window.get("title", "")) if isinstance(window, dict) else ""
    context.log(
        f"开始挖矿：窗口 {title or '未命名'}，"
        f"目标线路 {int(config.get('target_line', 14))}，方式 {mode}，模拟运行 {context.dry_run}"
    )

    started_at = time.monotonic()
    with context.step('检查采集疲劳'):
        _ensure_gathering_fatigue(context)
    with context.step('检查矿锄耐久'):
        _ensure_pickaxe_ready(context)
    with context.step("切换到目标线路"):
        if bool(config.get("switch_line_enabled", True)):
            _switch_line(context, int(config.get("target_line", 14)))
        else:
            context.log("已关闭自动换线，使用当前线路", "warning")
    with context.step("前往矿区"):
        if bool(config.get("skip_travel", False)):
            context.log("配置为跳过前往矿区，假定角色已经在矿区")
        elif config.get('travel_mode', 'actions') == 'code':
            _travel_by_code(context)
        else:
            if config.get('travel_mode', 'actions') != 'actions':
                raise ValueError('travel_mode 只能是 code 或 actions')
            travel = _normalize_actions(config.get("travel_actions", []), "travel_actions")
            if not travel:
                raise RuntimeError("没有配置 travel_actions；请先录入从当前起点到矿区的移动路线，或开启 skip_travel")
            _activate(context)
            for index, action in enumerate(travel, 1):
                context.log(f"前往矿区动作 {index}/{len(travel)}：{action['direction'] or '停留'} {action['seconds']:.2f}s")
                _hold_direction(context, action["direction"], action["seconds"], action["jump"])
                _wait(context, float(config.get("travel_action_pause", 0.3)))
    _wait(context, float(config.get("mine_entry_wait", 2)))

    if mode == "patrol_g":
        patrol = _normalize_actions(config.get("patrol_route", []), "patrol_route")
        if not patrol:
            raise RuntimeError("没有配置 patrol_route；请录入矿区四处巡逻动作")
        _run_patrol_g(context, patrol)
    else:
        if not use_templates:
            raise RuntimeError("template 模式必须启用 use_templates 并导入矿点模板")
        context.log("矿点识别方式：模板匹配（请确认已导入矿点模板）")
        _run_template_loop(context, region)

    elapsed = round(time.monotonic() - started_at, 1)
    context.debug.watch("mining_elapsed_seconds", elapsed)
    context.log(f"挖矿流程结束，耗时 {elapsed} 秒")

