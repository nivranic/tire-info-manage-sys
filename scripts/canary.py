"""Explicit live tire-source canary; offline tests mock every source fetch."""
import argparse
import asyncio
import json
import sys
import hashlib
from datetime import UTC, datetime

from tire_api.adapters import registry
from tire_api.parser_runtime import MAX_CONCURRENT

EXECUTION_SCOPE = 'installed_tire_source_code_without_database_deployment'


async def run() -> int:
    parser = argparse.ArgumentParser(description="访问公开官网，验证已登记轮胎 Adapter；不包含召回或车型来源，无数据库部署绑定")
    parser.add_argument("--source", default="michelin-us", help="明确选择一个已登记轮胎来源 ID")
    parser.add_argument("--model")
    parser.add_argument("--size", default="265/40R20")
    parser.add_argument("--all-sources", action="store_true", help="仅检查状态为 ready 的已登记轮胎 SourceSpec，不包含召回或车型来源")
    parser.add_argument("--revalidate", action="store_true", help="再次取正文核验；无数据库部署绑定，不跨代码复用条件缓存")
    args = parser.parse_args()
    sources = {source['id']: source for source in registry.sources()}
    source_ids = [source_id for source_id, source in sources.items()
                  if source['status'] == 'ready' and source_id in registry.SPECS] if args.all_sources else [args.source]

    async def check(source_id):
        spec = registry.SPECS.get(source_id)
        model = args.model or (next(iter(spec.model_urls), None) if spec else None)
        query = {'model': model} if model else {}
        if args.size:
            query["size"] = args.size
        if spec is None:
            source = sources.get(source_id)
            reason = ('source_not_found' if source is None else
                      source['status'] if source['status'] != 'ready' else 'unsupported_query_type')
            result = {'status': 'unavailable', 'reason': reason}
        else:
            result = await registry.fetch(source_id, query)
        report = {
            "checked_at": datetime.now(UTC).isoformat(), "source_id": source_id,
            "query": query, "status": result["status"], "reason": result.get("reason"),
            "source_url": result.get("url"), "parser_version": result.get("parser_version"),
            "execution_scope": EXECUTION_SCOPE,
            "parser_identity": result.get("parser_identity"), "parser_receipt": result.get("parser_receipt"),
            "variant_count": len(result.get("variants", [])),
            "product_codes": [v["manufacturer_product_code"] for v in result.get("variants", [])],
            "body_bytes": len(result.get("body", "").encode("utf-8")),
            "raw_hash": hashlib.sha256(result["body"].encode("utf-8")).hexdigest() if result.get("body") else None,
            "conflict_count": sum(len(v.get("facts", {}).get("source_field_conflicts", [])) for v in result.get("variants", [])),
            "response_validators_present": bool(result.get("etag") or result.get("last_modified")),
            "conditional_validation_available": False,
        }
        if args.revalidate and result['status'] == 'ok':
            await asyncio.sleep(max(2.1, registry._states[spec.origin]["interval"] + 0.1))
            verified = await registry.fetch(source_id, query, cached=result)
            report["revalidation"] = {"status": verified["status"], "reason": verified.get("reason"),
                                      "strategy": "unconditional_without_deployment_pin"}
        return report

    # Keep the canary's own fan-out within the host parser capacity. This is a
    # source check, not a deliberate queue-overload/resource-timeout experiment.
    slots = asyncio.Semaphore(MAX_CONCURRENT)
    async def bounded(source_id):
        async with slots:
            return await check(source_id)
    reports = await asyncio.gather(*(bounded(source_id) for source_id in source_ids))
    print(json.dumps(reports if args.all_sources else reports[0], ensure_ascii=False, indent=2))
    if not reports:
        print('没有状态为 ready 的已登记轮胎来源；未执行来源检查。', file=sys.stderr)
    passed = reports and all(report['status'] == 'ok' and
        (not args.revalidate or report.get('revalidation', {}).get('status') == 'ok') for report in reports)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
