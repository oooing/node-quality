"""Conservative IPPure recommendations from saved checks."""
from datetime import datetime, timedelta, timezone
import ipaddress
import math
import re


SHANGHAI = timezone(timedelta(hours=8))
REVIEW_HOURS = 24
LOW_RISK_THRESHOLD = 30
RELATIVE_THRESHOLD = 50


def _time(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        return result if result.tzinfo is not None and result.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def _score(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and 0 <= value <= 100 and math.isfinite(value))


# Subscription labels describe the chosen route; these are not IP geolocation results.
REGION_CODES = dict(pair.split(':') for pair in '香港:HK 台湾:TW 澳门:MO 中国:CN 日本:JP 韩国:KR 新加坡:SG 美国:US 英国:GB 德国:DE 法国:FR 加拿大:CA 澳大利亚:AU 俄罗斯:RU 印度:IN 印尼:ID 马来西亚:MY 泰国:TH 越南:VN 菲律宾:PH 巴西:BR 阿根廷:AR 南非:ZA 尼日利亚:NG 阿联酋:AE 土耳其:TR 荷兰:NL 意大利:IT 西班牙:ES 瑞士:CH 瑞典:SE 芬兰:FI 挪威:NO 丹麦:DK 冰岛:IS 爱尔兰:IE 葡萄牙:PT 比利时:BE 卢森堡:LU 波兰:PL 捷克:CZ 匈牙利:HU 希腊:GR 罗马尼亚:RO 保加利亚:BG 斯洛文尼亚:SI 北马其顿:MK 立陶宛:LT 拉脱维亚:LV 爱沙尼亚:EE 新西兰:NZ 墨西哥:MX 智利:CL 秘鲁:PE 哥伦比亚:CO 巴拿马:PA 埃及:EG 以色列:IL 伊朗:IR 伊拉克:IQ 亚美尼亚:AM 阿塞拜疆:AZ 柬埔寨:KH 缅甸:MM 老挝:LA 文莱:BN 巴基斯坦:PK 尼泊尔:NP 不丹:BT 斯里兰卡:LK 蒙古:MN 东帝汶:TL 巴布亚:PG 关岛:GU 斐济:FJ 列支敦士登:LI 梵蒂冈:VA 格陵兰:GL 波多黎各:PR 古巴:CU'.split())
REGION_NAMES = {code: name for name, code in REGION_CODES.items()}
REGION_ALIASES = {'Hong Kong':'HK', 'Taiwan':'TW', 'Japan':'JP', 'Singapore':'SG', 'United States':'US', 'United Kingdom':'GB', 'Korea':'KR', 'Australia':'AU', 'Canada':'CA', 'Germany':'DE', 'France':'FR', '新加坡':'SG', '狮城':'SG', '美國':'US', '香港':'HK', '台灣':'TW', '韓國':'KR'}
def node_region(node):
    name = node.get('name', '')
    for label, code in {**REGION_CODES, **REGION_ALIASES}.items():
        if label.casefold() in name.casefold():
            return code
    flag = re.search('[\U0001f1e6-\U0001f1ff]{2}', name)
    if flag:
        return ''.join(chr(ord(c) - 0x1f1e6 + 65) for c in flag.group())
    for code in REGION_NAMES:
        if re.search(r'(?<![A-Za-z])' + code + r'(?![A-Za-z])', name, re.I):
            return code
    return 'UNKNOWN'

def normalize_options(options=None):
    """Validate recommendation settings and return independent numeric defaults."""
    values = {'max_risk': LOW_RISK_THRESHOLD, 'regions': []}
    if options is not None:
        if not isinstance(options, dict) or any(key not in (*values, 'fresh_hours', 'limit') for key in options):
            raise ValueError('推荐设置无效，请重新保存。')
        # Older installs saved expiry/display limits. These no longer affect selection.
        values.update({k: v for k, v in options.items() if k in values})
    if not _score(values['max_risk']):
        raise ValueError('风险上限需填写 0–100 之间的数值。')
    if 'regions' in values:
        regions = values['regions']
        if not isinstance(regions, list) or any(not isinstance(r, str) or not re.fullmatch(r'[A-Z]{2}|UNKNOWN', r) for r in regions):
            raise ValueError('地区选择无效，请重新选择。')
        values['regions'] = list(dict.fromkeys(regions))
    max_risk = values['max_risk']
    values['max_risk'] = int(max_risk) if float(max_risk).is_integer() else max_risk
    return values


def _ip(value):
    if not isinstance(value, str):
        return None
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError:
        return None


def _result(record):
    """Only a verified IPPure result can support a node recommendation."""
    if (not isinstance(record, dict) or record.get('status') != 'ok'
            or record.get('route_verified') is not True):
        return None
    when = _time(record.get('checked_at'))
    ip = _ip(record.get('ip'))
    if when is None or ip is None or not _score(record.get('score')):
        return None
    return {'ip': ip, 'scores': {'ippure': record['score']}, 'time': when}


def _timeline(node, histories):
    records = [node.get('last_attempt'), *histories.get(node['id'], []), node.get('latest')]
    unique = {}
    for record in records:
        if isinstance(record, dict):
            when = _time(record.get('checked_at'))
            if when is not None and when not in unique:
                unique[when] = record
    return [unique[when] for when in sorted(unique, reverse=True)][:10]


def assess_node(node, now=None):
    """Separate connection failure from an unavailable rating; never refresh old scores."""
    now = now or datetime.now(SHANGHAI)
    attempt = node.get('last_attempt')
    latest = node.get('latest')
    if node.get('config_changed') or node.get('unsupported'):
        return {'state': 'unrated', 'needs_review': False}
    if attempt and _time(attempt.get('checked_at')) is None:
        return {'state': 'unrated', 'needs_review': False}
    if attempt and attempt.get('status') != 'ok':
        observed = _ip(attempt.get('observed_ip') or node.get('observed_ip'))
        if observed and latest and observed != latest.get('ip'):
            return {'state': 'ip_changed', 'needs_review': True}
        if attempt.get('connectivity', {}).get('status') != 'ok':
            return {'state': 'connection_failed', 'needs_review': False}
        state = 'score_pending'
        record = latest
    else:
        state = 'current'
        record = attempt or latest
    result = _result(record)
    if result is None or result['time'] > now:
        return {'state': state if state == 'score_pending' else 'unrated', 'needs_review': True}
    if state == 'current' and now - result['time'] >= timedelta(hours=REVIEW_HOURS):
        state = 'review'
    return {'state': state, 'needs_review': state != 'current', 'record': record}


def _stats(records, current):
    results = [_result(record) for record in records]
    consecutive = 0
    for result in results:
        if result is None:
            break
        consecutive += 1
    failures = sum(record.get('status') != 'ok' for record in records)
    ips = [result['ip'] for result in results if result]
    changes = sum(before != after for before, after in zip(ips, ips[1:]))
    previous = next((result for result in results[1:] if result), None)
    previous_ip = previous['ip'] if previous else None
    increases = {}
    if previous is not None and current['scores']['ippure'] > previous['scores']['ippure']:
        increases['ippure'] = round(current['scores']['ippure'] - previous['scores']['ippure'], 3)
    span = (current['time'] - _time(records[-1]['checked_at'])).total_seconds() / 3600
    return {'consecutive_successes': consecutive, 'recent_failures': failures,
            'ip_changes': changes, 'last_ip_changed': previous_ip is not None and previous_ip != current['ip'],
            'risk_increases': increases, 'observed_hours': round(max(0, span), 2),
            'sample_count': len(records), 'ippure_successes': sum(result is not None for result in results)}


def _candidate(node, record, result, records, category, now):
    stats = _stats(records, result)
    reasons = []
    if stats['consecutive_successes'] >= 2:
        reasons.append(f"最近 {stats['consecutive_successes']} 次 IPPure 检测连续成功")
    elif stats['ippure_successes'] == 1:
        reasons.append('仅有一次 IPPure 成功记录，稳定性仍待观察')
    warnings = []
    if stats['recent_failures']:
        warnings.append(f"最近 {stats['sample_count']} 次中有 {stats['recent_failures']} 次 IPPure 检测未完成")
    if stats['last_ip_changed']:
        warnings.append('本次出口 IP 与上次成功检测不同')
    elif stats['ip_changes']:
        warnings.append(f"最近记录中出口 IP 变化 {stats['ip_changes']} 次")
    if stats['risk_increases']:
        warnings.append(f"风险评分较上次升高：+{stats['risk_increases']['ippure']:g}")
    return {'id': node['id'], 'name': node['name'], 'ip': result['ip'],
            'source': 'IPPure', 'scores': result['scores'], 'category': category,
            'label': {'low_risk': '低风险', 'relative': '备选', 'high_risk': '风险偏高'}[category],
            'classification_source': 'panel_policy',
            'checked_at': record['checked_at'], 'reasons': reasons, 'warnings': warnings,
            'stats': stats, 'age_hours': round((now - result['time']).total_seconds() / 3600, 3)}


def _history_order(item):
    stats = item['stats']
    return (stats['recent_failures'], stats['last_ip_changed'], stats['ip_changes'],
            bool(stats['risk_increases']), -stats['consecutive_successes'],
            -stats['observed_hours'], item['age_hours'], item['id'])


def rank_nodes(nodes, histories, now=None, options=None):
    """Rank verified IPPure results within the explicit range, without any IO."""
    options = normalize_options(options)
    now = datetime.now(SHANGHAI) if now is None else _time(now)
    if now is None:
        raise ValueError('now must include a timezone')
    counts = dict.fromkeys(('total', 'low_risk', 'relative', 'incomplete', 'failed',
                            'stale', 'high_risk', 'unsupported', 'eligible', 'over_max_risk', 'matching_region'), 0)
    candidates = []
    valid_scores = []
    for node in nodes:
        counts['total'] += 1
        if options.get('regions') and node_region(node) not in options['regions']:
            continue
        counts['matching_region'] += 1
        if node.get('unsupported'):
            counts['unsupported'] += 1
            continue
        assessment = assess_node(node, now)
        # An undated last attempt must not silently fall back to an older success.
        attempt = node.get('last_attempt')
        if isinstance(attempt, dict) and _time(attempt.get('checked_at')) is None:
            counts['failed' if attempt.get('status') != 'ok' else 'incomplete'] += 1
            continue
        records = _timeline(node, histories)
        if not records:
            counts['incomplete'] += 1
            continue
        record = assessment.get('record')
        if not record:
            counts['failed' if assessment['state'] == 'connection_failed' else 'incomplete'] += 1
            continue
        age = now - _time(record.get('checked_at'))
        if assessment['needs_review']:
            counts['stale'] += 1
        if age < timedelta(0):
            counts['incomplete'] += 1
            continue
        result = _result(record)
        if result is None:
            counts['incomplete'] += 1
            continue
        valid_scores.append(result['scores']['ippure'])
        if result['scores']['ippure'] <= LOW_RISK_THRESHOLD:
            category = 'low_risk'
        elif result['scores']['ippure'] <= RELATIVE_THRESHOLD:
            category = 'relative'
        else:
            category = 'high_risk'
        counts[category] += 1
        if result['scores']['ippure'] > options['max_risk']:
            counts['over_max_risk'] += 1
            continue
        candidate = _candidate(node, record, result, records, category, now)
        candidate.update(state=assessment['state'], needs_review=assessment['needs_review'])
        candidates.append(candidate)
    counts['eligible'] = len(candidates)
    items = sorted(candidates, key=lambda item: (item['needs_review'], item['scores']['ippure'], *_history_order(item)))
    status = 'ready' if items else 'none'
    message = f"找到 {len(candidates)} 条风险 ≤ {options['max_risk']:g} 的线路。"
    if not items:
        selected = options.get('regions', [])
        scope = '、'.join(REGION_NAMES.get(code, '未识别' if code == 'UNKNOWN' else code) for code in selected) if len(selected) <= 3 else '所选地区'
        scope = scope or '当前列表'
        if not counts['matching_region']:
            message = f'{scope}没有线路。'
        else:
            reasons = []
            if counts['over_max_risk']:
                reasons.append(f"{counts['over_max_risk']} 个 IPPure 风险超过 {options['max_risk']:g}（最低 {min(valid_scores):g}）")
            for key, label in [('failed', '连接未确认'), ('incomplete', '尚无可用评分'),
                               ('unsupported', '暂不支持检测')]:
                if counts[key]:
                    reasons.append(f"{counts[key]} 个{label}")
            message = f"{scope} {counts['matching_region']} 条线路暂不符合推荐条件：\n" + '\n'.join(reasons)
    return {'regions': [{'id': code, 'name': REGION_NAMES.get(code, '未识别' if code == 'UNKNOWN' else code)} for code in sorted({node_region(node) for node in nodes})], 'items': items, 'status': status, 'message': message, 'counts': counts, 'source': 'IPPure',
            'options': options, 'review_hours': REVIEW_HOURS, 'low_risk_threshold': LOW_RISK_THRESHOLD,
            'relative_threshold': RELATIVE_THRESHOLD,
            'generated_at': now.astimezone(SHANGHAI).isoformat(timespec='seconds')}
