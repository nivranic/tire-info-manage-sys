"""Fixed Michelin regional resources verified through public HTTP on 2026-09-26.

US keeps its existing registry definition. Each region remains a separate source
and product identity scope, even when two catalogues share a CAI or EAN.
"""

MICHELIN_REGIONS = {
    "michelin-uk": {
        "name": "Michelin 英国",
        "region": "UK",
        "origin": "https://www.michelin.co.uk",
        "model_urls": {
            "Pilot Sport EV": "https://www.michelin.co.uk/auto/tyres/michelin-pilot-sport-ev",
            "Pilot Sport 4 S": "https://www.michelin.co.uk/auto/tyres/michelin-pilot-sport-4-s",
        },
        "parser_version": "michelin-astro-v2",
        "description": "英国官方 SSR 目录；保留 CAI/EAN、型号规格、标签与同页字段冲突。",
        "status": "ready",
        "verified": True,
        "verified_at": "2026-09-26",
        "notes": "两产品页与 robots 均 200，无重定向；text/html。PSEV 67 条，PS4S 209 条。仅固定 www 域名；不访问 robots 禁止的 /api/ 或带筛选查询参数的页面。",
    },
    "michelin-fr": {
        "name": "Michelin 法国",
        "region": "FR",
        "origin": "https://www.michelin.fr",
        "model_urls": {
            "Pilot Sport EV": "https://www.michelin.fr/auto/tyres/michelin-pilot-sport-ev",
            "Pilot Sport 4 S": "https://www.michelin.fr/auto/tyres/michelin-pilot-sport-4-s",
        },
        "parser_version": "michelin-astro-v2",
        "description": "法国官方 SSR 目录；CAI 与 MSPN 分开命名，保留厂商标签声明。",
        "status": "ready",
        "verified": True,
        "verified_at": "2026-09-26",
        "notes": "两产品页与 robots 均 200，无重定向；text/html。PSEV 67 条，PS4S 209 条。robots 除其他区域相同限制外还禁止 *page=。",
    },
    "michelin-de": {
        "name": "Michelin 德国",
        "region": "DE",
        "origin": "https://www.michelin.de",
        "model_urls": {
            "Pilot Sport EV": "https://www.michelin.de/auto/tyres/michelin-pilot-sport-ev",
            "Pilot Sport 4 S": "https://www.michelin.de/auto/tyres/michelin-pilot-sport-4-s",
        },
        "parser_version": "michelin-astro-v2",
        "description": "德国官方 SSR 目录；区域身份独立，显式保留源字段冲突。",
        "status": "ready",
        "verified": True,
        "verified_at": "2026-09-26",
        "notes": "两产品页与 robots 均 200，无重定向；text/html。PSEV 67 条，PS4S 209 条。仅固定 www 域名；未放宽到域名别名。",
    },
    "michelin-cn": {
        "name": "Michelin 中国",
        "region": "CN",
        "origin": "https://www.michelin.com.cn",
        "model_urls": {
            "Pilot Sport EV": "https://www.michelin.com.cn/auto/tyre-selector/assets/js/specs_by_size_pattern.js",
            "Pilot Sport 4 S": "https://www.michelin.com.cn/auto/tyre-selector/assets/js/specs_by_size_pattern.js",
        },
        "product_page_urls": {
            "Pilot Sport EV": "https://www.michelin.com.cn/auto/tyre-selector/by-pattern/detail/PILOT%20SPORT%20EV",
            "Pilot Sport 4 S": "https://www.michelin.com.cn/auto/tyre-selector/by-pattern/detail/PILOT%20SPORT%204S",
        },
        "content_types": ("text/javascript", "application/javascript", "text/plain"),
        "parser_version": "michelin-cn-catalog-v1",
        "description": "中国官网公开静态目录 JSON 字面量；不执行 JavaScript，保留 CAI 与原始标记，不补造 EU/US 字段。",
        "status": "ready",
        "verified": True,
        "verified_at": "2026-09-26",
        "notes": "robots 允许固定 assets/js 路径。目录 200 text/javascript，无重定向；全部 1372 条，PSEV 74 条、PS4S 159 条。公开 product/index.js 明确 item.cai=item.c。m 混含 OE/厂商标记，先保留 source_markings，未全部推断为 OE；缺失 XL/HL/EAN/UTQG 保持未知。",
    },
}
