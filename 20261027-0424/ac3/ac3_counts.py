import sqlite3, sys, json
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
q = lambda s, *a: con.execute(s, a).fetchall()
print("alembic", q("select version_num from alembic_version"))
print("by version/status", q("select prompt_version, llm_status, count(*) from news_llm_results group by 1,2 order by 1,2"))
# items whose AI block the base rule shows from news_v1: latest done/rejected (by llm_run_at desc, id desc) is news_v1 done
rows = q("""
with ranked as (
  select news_item_id, prompt_version, llm_status,
         row_number() over (partition by news_item_id order by llm_run_at desc, id desc) rn
  from news_llm_results where llm_status in ('done','rejected'))
select prompt_version, llm_status, count(*) from ranked where rn=1 group by 1,2 order by 1,2""")
print("base shows (latest done/rejected per item)", rows)
print("items with v1 done and no v2 done", q("""
select count(distinct news_item_id) from news_llm_results r where prompt_version='news_v1' and llm_status='done'
and not exists (select 1 from news_llm_results v where v.news_item_id=r.news_item_id and v.prompt_version='news_v2' and v.llm_status='done')"""))
print("items with v2 done", q("select count(*) from news_llm_results where prompt_version='news_v2' and llm_status='done'"))
for nid in (2435, 2458):
    print(nid, q("select id, prompt_version, llm_status, llm_model, llm_run_at, ai_summary from news_llm_results where news_item_id=? order by id", nid))
