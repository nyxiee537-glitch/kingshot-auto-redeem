from __future__ import annotations
import json,os,time
from dataclasses import dataclass
from pathlib import Path
from api_client import FATAL_CODE_STATUSES,redeem_once
from config import *
from test_notion import get_active_players,get_data_source_id

@dataclass
class RedeemResult:
    name:str; status:str; message:str; player_id:str=""

def redeem_player(p,code,n):
    name=p.get("name","").strip() or f"Player-{n}"
    fid=p.get("player_id","").strip(); kid=p.get("kingdom","").strip()
    if not fid:return RedeemResult(name,"failed","Player IDが空です。",fid)
    if not kid:return RedeemResult(name,"failed","Kingdomが空です。",fid)
    print(f"[{n}] {name} | K{kid} | ***{fid[-4:]}")
    r=redeem_once(fid,kid,code)
    return RedeemResult(name,r.status,r.message,fid)

def load_validation():
    fn=os.environ.get("VALIDATION_RESULTS_FILE","").strip()
    if not fn or not Path(fn).exists(): return {}
    try:d=json.loads(Path(fn).read_text(encoding="utf-8"))
    except Exception:return {}
    return {str(v.get("player_id","")).strip():v for v in d.values()
            if isinstance(v,dict) and str(v.get("player_id","")).strip()}

def save_summary(code,results,fatal="",api_outage=False,restricted=False):
    counts={}
    for r in results:counts[r.status]=counts.get(r.status,0)+1
    s={"gift_code":code,"total_players":len(results),"counts":counts,"fatal_code_status":fatal,"api_outage":api_outage,"restricted":restricted,
       "results":[{"name":r.name,"status":r.status,"message":r.message} for r in results]}
    SUMMARY_JSON_FILE.write_text(json.dumps(s,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=[f"Gift code: {code}",f"Total processed: {len(results)}","","Summary:"]
    lines += [f"- {k}: {v}" for k,v in sorted(counts.items())]
    lines += ["","Players:"]+[f"- {r.name} | {r.status} | {r.message}" for r in results]
    SUMMARY_TEXT_FILE.write_text("\n".join(lines)+"\n",encoding="utf-8")
    return s

def main():
    code=os.environ["GIFT_CODE"].strip()
    players=get_active_players(get_data_source_id(os.environ["NOTION_DATABASE_ID"]))
    if not players:raise RuntimeError("NotionにActiveのプレイヤーがいません。")
    RESULTS_DIR.mkdir(parents=True,exist_ok=True)
    validation=load_validation(); results=[]; queue=[]; fatal=""; consecutive_api_failures=0; api_outage=False
    restricted=any(v.get("status")=="requirements_not_met" for v in validation.values())
    print(f"Gift code: {code} | Active: {len(players)} | Direct API")

    for i,p in enumerate(players,1):
        fid=p.get("player_id","").strip()
        if fid in validation:
            v=validation[fid]
            r=RedeemResult(p.get("name","").strip() or v.get("name","") or f"Player-{i}",
                           v.get("status","unknown"),v.get("message",""),fid)
            print(f"[{i}] {r.name} | validator result reused: {r.status}")
        else:r=redeem_player(p,code,i)

        if r.status in FATAL_CODE_STATUSES:
            results.append(r);fatal=r.status;break

        # server_busy/unknown here means the API itself could not be used
        # reliably after api_client's own retries. Stop after N consecutive
        # failures instead of hammering every remaining account.
        if r.status in {"server_busy","unknown"}:
            consecutive_api_failures += 1
        else:
            consecutive_api_failures = 0

        if r.status=="rate_limited":
            print(f"  ↪️ {r.name}: TOO FREQUENT → retry queue")
            queue.append([p,i,0])
        else:
            results.append(r)

        if consecutive_api_failures >= API_CONSECUTIVE_FAILURE_LIMIT:
            api_outage=True
            print(f"🛑 API unavailable/unreliable for {consecutive_api_failures} consecutive players. Stopping this run.")
            break

        if i<len(players):time.sleep(API_PLAYER_INTERVAL_SECONDS)

    while queue and not fatal and not api_outage:
        p,i,attempt=queue.pop(0); attempt+=1
        # Other players have already continued. Only wait when the retry queue
        # itself cycles back too quickly.
        if not queue:time.sleep(API_RATE_LIMIT_RETRY_SECONDS)
        r=redeem_player(p,code,i)
        if r.status in FATAL_CODE_STATUSES:
            results.append(r);fatal=r.status;break
        if r.status=="rate_limited" and attempt<API_RATE_LIMIT_MAX_RETRIES:
            queue.append([p,i,attempt]);continue
        results.append(r)

    print(json.dumps(save_summary(code,results,fatal,api_outage,restricted),ensure_ascii=False,indent=2))

if __name__=="__main__":main()
