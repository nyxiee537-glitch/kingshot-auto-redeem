from __future__ import annotations
import json,os
from pathlib import Path
import requests
from config import DISCORD_WEBHOOK_URL,HTTP_TIMEOUT
ERROR_WEBHOOK_URL=os.environ.get("DISCORD_ERROR_WEBHOOK_URL","").strip()

def _post(payload,attachment=None,error=False):
    url=ERROR_WEBHOOK_URL if error and ERROR_WEBHOOK_URL else DISCORD_WEBHOOK_URL
    if not url:return
    if attachment and Path(attachment).exists():
        with Path(attachment).open("rb") as f:
            r=requests.post(url,data={"payload_json":json.dumps(payload,ensure_ascii=False)},
              files={"files[0]":(Path(attachment).name,f,"text/plain")},timeout=HTTP_TIMEOUT)
    else:r=requests.post(url,json=payload,timeout=HTTP_TIMEOUT)
    r.raise_for_status()

def send_detection_notification(code,sources):
    src=" / ".join(sources) if sources else "不明"
    _post({"username":"537 Gift Bot","content":
      f"🎁 **新しい有効なギフトコードを検出しました**\n**Code:** `{code}`\n**Source:** {src}\n\n⚡ APIで有効性を確認済み。登録アカウントへの交換を開始します。",
      "allowed_mentions":{"parse":[]}})

def send_redeem_notification(code,sources,summary,summary_file):
    rs=summary.get("results",[])
    n=lambda s:sum(1 for r in rs if r.get("status")==s)
    src=" / ".join(sources) if sources else "不明"
    lines=["👑 **537 Gift Bot・ギフトコード交換完了**",f"**Code:** `{code}`",f"**Source:** {src}","",
      f"👥 対象: **{len(rs)}人**",f"✅ Success: **{n('success')}人**",f"☑️ Already: **{n('already_redeemed')}人**",
      f"🔒 条件未達: **{n('requirements_not_met')}人**"]
    for s,label in [("character_info_error","⚠️ Character情報エラー"),("player_not_found","⚠️ Player未検出"),("failed","❌ Failed")]:
        if n(s):lines.append(f"{label}: **{n(s)}人**")
    lines+=["","📎 詳細結果"]
    _post({"username":"537 Gift Bot","content":"\n".join(lines),"allowed_mentions":{"parse":[]}},summary_file)
    bad=[r for r in rs if r.get("status") in {"character_info_error","player_not_found"}]
    if bad:
        e=["⚠️ **537 Gift Bot・アカウント情報エラー**","Player ID / Kingdom情報をAPIで確認できないアカウントがあります。","移民とは断定せず、登録情報を確認してください。",""]
        for r in bad:e += [f"• **{r.get('name','Unknown')}**",f"  └ {r.get('message','')}"]
        _post({"username":"537 Gift Bot","content":"\n".join(e),"allowed_mentions":{"parse":[]}},error=True)

def send_source_error_notification(errors):
    if not errors:return
    lines=["⚠️ **537 Gift Bot・取得元エラー**","ギフトコード取得元でエラーが発生しました。",""]
    for k,v in errors.items():lines.append(f"• **{k}**: {str(v)[:500]}")
    _post({"username":"537 Gift Bot","content":"\n".join(lines),"allowed_mentions":{"parse":[]}},error=True)
