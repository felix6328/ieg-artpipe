"""把 0 A.D. 252 条美术 Issue（官方 Gitea API 快照）按标题分 3 桶，并统计修复时长。纯离线。
用法：先按 research/README.md 用 Gitea 公开 API 抓取 art_issues.json（含公开账号元数据，不入库），再运行 python3 docs/research/categorize_0ad.py research/art_issues.json"""
import json, re, csv, statistics, datetime as dt, sys
d = json.load(open(sys.argv[1]))
A = r'missing|not found|broken|wrong|incorrect|duplicat|renam|naming|unused|resolution|\bdds\b|\bpng\b|\bformat\b|error|warning|crash|invalid|reference|non-existent|nonexist|npot|power of two|bad path|typo|doesn.t exist|outdated|corrupt|assert|pngcheck'
B = r'^(unit|structure|animal|hero|ship|building|prop)s?:|need(s)? (a )?new|create new|new model|new animation|has no .*animation|have no .*animation|no .*animation|^\[?art\]?:? ?add|replace|improve|redo|remake'
out = []
for x in d:
    t = x['title'].lower()
    b = 'A 机器可检(缺失/断引用/格式/重复/报错)' if re.search(A, t) else ('B 内容缺口/新资产需求' if re.search(B, t) else 'C 质量/表现/其他(需人判断)')
    L = {l['name'] for l in x['labels']}
    get = lambda pre: next((l.split('/', 1)[1] for l in L if l.startswith(pre)), '')
    days = (dt.datetime.fromisoformat(x['closed_at']) - dt.datetime.fromisoformat(x['created_at'])).days if x['closed_at'] and get('Closed/') == 'Fixed' else ''
    out.append(dict(number=x['number'], url=x['html_url'], title=x['title'], bucket=b, type=get('Type/'), priority=get('Priority/'),
                    closed_as=get('Closed/'), state=x['state'], created=x['created_at'][:10], closed=(x['closed_at'] or '')[:10], days_to_fix=days, comments=x['comments']))
with open('0ad_art_issues_categorized.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
S = {}
for b in sorted({o['bucket'] for o in out}):
    v = [o for o in out if o['bucket'] == b]; fx = [o['days_to_fix'] for o in v if o['days_to_fix'] != '']
    S[b] = dict(n=len(v), share=round(len(v)/len(out), 3), defect=sum(o['type'] == 'Defect' for o in v), fixed=len(fx),
                median_days=statistics.median(fx) if fx else None, over_90d=sum(z > 90 for z in fx), over_365d=sum(z > 365 for z in fx),
                open=sum(o['state'] == 'open' for o in v), must_or_blocker=sum(o['priority'].startswith(('1', '2')) for o in v))
json.dump(S, open('0ad_bucket_stats.json', 'w'), ensure_ascii=False, indent=1)
print(json.dumps(S, ensure_ascii=False, indent=1))
