"""Local read-only Evidence Core viewer with trace and trajectory projections."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

from evidence_core.reader import EvidenceReader
from evidence_core.store.fs_store import EvidenceStore


INDEX_HTML = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Evidence Viewer</title><style>
:root{color-scheme:dark;font:13px/1.45 ui-sans-serif,system-ui;background:#0b0f14;color:#e6edf3}*{box-sizing:border-box}body{margin:0}header{height:62px;border-bottom:1px solid #27313d;display:flex;align-items:center;padding:0 24px;gap:12px;background:#0f141b}header h1{font-size:16px;margin:0;font-weight:650}header .sub{color:#7d8996;font-size:12px}.layout{display:grid;grid-template-columns:330px 1fr;min-height:calc(100vh - 62px)}aside{border-right:1px solid #27313d;padding:16px 13px;overflow:auto}.content{padding:24px 28px;overflow:auto}.search,.select{width:100%;background:#121923;color:inherit;border:1px solid #2c3947;border-radius:6px;padding:8px 10px;margin-bottom:8px}.filters{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-bottom:14px}.run{padding:11px 10px;border:1px solid transparent;border-radius:7px;cursor:pointer;margin-bottom:6px}.run:hover,.run.active{background:#151d27;border-color:#3a4a5b}.run .top{display:flex;justify-content:space-between;gap:8px}.run .id{font:10px ui-monospace;color:#8491a0}.run .goal{margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.muted{color:#8491a0}.status{font-size:10px;border-radius:12px;padding:2px 7px;background:#202a35}.status.success{color:#4bd26f}.status.failed{color:#ff6b6b}.status.blocked{color:#f2bd5d}.hero{display:flex;justify-content:space-between;gap:20px;align-items:flex-start}.eyebrow{font-size:10px;letter-spacing:.1em;color:#7d8996;text-transform:uppercase}.hero h2{margin:4px 0 4px;font-size:21px;line-height:1.25}.button{background:#2f81f7;border:0;color:#fff;border-radius:6px;padding:8px 11px;cursor:pointer}.stats{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0}.stat{background:#121923;border:1px solid #2c3947;border-radius:7px;padding:10px 13px;min-width:118px}.stat b{display:block;font-size:17px}.section{margin-top:23px}.section h3{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:#8491a0;margin:0 0 9px}.tabs{display:flex;gap:4px;border-bottom:1px solid #27313d;margin-top:22px}.tab{background:transparent;color:#8491a0;border:0;padding:9px 12px;cursor:pointer;border-bottom:2px solid transparent}.tab.active{color:#e6edf3;border-color:#2f81f7}.timeline{position:relative;border-left:1px solid #344252;margin-left:10px}.event{position:relative;padding:0 0 13px 21px;cursor:pointer}.event:before{content:"";position:absolute;left:-5px;top:5px;width:8px;height:8px;border-radius:50%;background:#58a6ff;border:2px solid #0b0f14}.event.failed:before{background:#ff6b6b}.event.selected{background:#141e2a;border-radius:6px}.event .row{display:flex;gap:9px;align-items:center}.event .seq{font:10px ui-monospace;color:#8491a0}.phase{font-size:10px;color:#9aa9b8;background:#1a2531;padding:1px 6px;border-radius:10px}.event details{margin-top:6px;background:#111923;border:1px solid #2c3947;border-radius:6px;padding:8px}.event pre,.inspector pre{white-space:pre-wrap;overflow:auto;color:#c9d1d9;font:11px/1.45 ui-monospace}.inspector{background:#111923;border:1px solid #2c3947;border-radius:7px;padding:13px}.inspector h4{margin:0 0 8px;font-size:12px}.inspector pre{max-height:280px}.artifact{display:flex;justify-content:space-between;border-bottom:1px solid #202b36;padding:8px 0}.empty{color:#8491a0;padding:40px 0}.legend{display:flex;gap:12px;color:#8491a0;font-size:11px;margin:9px 0}.legend span:before{content:"";display:inline-block;width:7px;height:7px;background:#58a6ff;border-radius:50%;margin-right:5px}.legend .bad:before{background:#ff6b6b}@media(max-width:850px){.layout{grid-template-columns:1fr}aside{max-height:42vh;border-right:0;border-bottom:1px solid #27313d}.content{padding:18px}.filters{grid-template-columns:1fr 1fr}}
</style></head><body><header><h1>Evidence Viewer</h1><span class="sub">trace debugging · read-only evidence</span></header><div class="layout"><aside><input id="q" class="search" placeholder="Search goal, task, run…"><div class="filters"><select id="status" class="select"><option value="">All statuses</option><option>success</option><option>failed</option><option>blocked</option><option>running</option></select><select id="verify" class="select"><option value="">All verification</option><option>passed</option><option>failed</option><option>blocked</option><option>not_started</option></select></div><div id="runs"></div></aside><main class="content" id="detail"><div class="empty">Select a run. The overview answers what happened; the timeline answers how; the inspector shows the evidence.</div></main></div><script>
const $=s=>document.querySelector(s);let all=[],selected='',current=null,mode='trajectory',selectedSeq=null;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const pretty=v=>esc(JSON.stringify(v,null,2));
function filtered(){const q=$('#q').value.toLowerCase(),st=$('#status').value,ve=$('#verify').value;return all.filter(r=>(!st||r.final_status===st)&&(!ve||r.verification_status===ve)&&(r.run_id+' '+r.task_id+' '+r.goal+' '+r.final_status).toLowerCase().includes(q))}
function renderRuns(){$('#runs').innerHTML=filtered().map(r=>`<div class="run ${selected===r.run_id?'active':''}" data-run="${esc(r.run_id)}"><div class="top"><span class="id">${esc(r.run_id.slice(0,12))}</span><span class="status ${esc(r.final_status)}">${esc(r.final_status||'running')}</span></div><div class="goal">${esc(r.goal||r.task_id)}</div><div class="muted">${r.event_count||0} events · ${r.tool_called_count||0} tools · ${esc(r.verification_status||'not_started')}</div></div>`).join('')||'<div class="empty">No matching runs.</div>';document.querySelectorAll('[data-run]').forEach(x=>x.onclick=()=>loadRun(x.dataset.run))}
function eventClass(e){return (e.event_type.includes('failed')||e.payload?.success===false)?'failed':''}
function eventLabel(e){return e.event_type.replaceAll('_',' ')}
function renderInspector(e){if(!e)return '<div class="muted">Select a step to inspect its evidence.</div>';const p=e.payload||{},command=p.command||p.requested_command,hasOutput=p.stdout!==undefined||p.stderr!==undefined||p.exit_code!==undefined;const evidence=command?`<div><b>Command</b><pre>${esc(command)}</pre></div>`:'';const result=hasOutput?`<div><b>Result · exit code ${esc(p.exit_code??'—')}</b><pre>stdout:\n${esc(p.stdout||'')}\nstderr:\n${esc(p.stderr||'')}</pre></div>`:'';const validation=p.verification_status||p.success!==undefined?`<div><b>Outcome</b><pre>${pretty({success:p.success,verification_status:p.verification_status,reason:p.reason})}</pre></div>`:'';return `<div class="inspector"><h4>#${e.sequence} · ${esc(eventLabel(e))}</h4><div class="muted">${esc(e.summary||'')} · phase: ${esc(e.phase||'')} · recorded ${esc(e.created_at||'')}</div><div class="tabs"><button class="tab active">Summary</button><button class="tab">Input / Output</button><button class="tab">Raw Evidence</button></div>${evidence}${result}${validation}<details><summary>Raw payload</summary><pre>${pretty(p)}</pre></details></div>`}
function renderTrajectory(d){return `<div class="section"><h3>Step-by-step trajectory</h3><div class="legend"><span>normal event</span><span class="bad">failed or negative result</span></div><div class="timeline">${d.events.map(e=>`<div class="event ${eventClass(e)} ${selectedSeq===e.sequence?'selected':''}" data-seq="${e.sequence}"><div class="row"><span class="seq">#${e.sequence}</span><strong>${esc(eventLabel(e))}</strong><span class="phase">${esc(e.phase||'')}</span></div><div>${esc(e.summary||'')}</div></div>`).join('')}</div></div><div class="section"><h3>Evidence inspector</h3>${renderInspector(d.events.find(e=>e.sequence===selectedSeq))}</div>`}
function renderTrace(d){return `<div class="section"><h3>Trace tree</h3><div class="timeline">${d.events.map(e=>`<div class="event ${eventClass(e)}"><div class="row"><span class="seq">#${e.sequence}</span><strong>${esc(eventLabel(e))}</strong><span class="phase">${esc(e.phase||'')}</span></div><div>${esc(e.summary||'')}</div></div>`).join('')}</div><p class="muted">Trace view keeps execution order and phase boundaries. Parent/child lineage will use typed correlation fields as the corpus grows.</p></div>`}
function renderRaw(d){return `<div class="section"><h3>Raw events</h3><div class="inspector"><pre>${pretty(d.events)}</pre></div></div>`}
function durationLabel(r){if(!r.finished_at||!r.started_at)return '—';const ms=Math.max(0,new Date(r.finished_at)-new Date(r.started_at));return ms<1000?ms+'ms':(ms/1000).toFixed(1)+'s'}
async function loadRun(id){selected=id;selectedSeq=null;renderRuns();const response=await fetch('/api/runs/'+id);if(!response.ok){$('#detail').innerHTML='<div class="empty">Unable to load this run.</div>';return}current=await response.json();renderDetail()}
function renderDetail(){const d=current,r=d.run,s=d.summary;$('#detail').innerHTML=`<div class="hero"><div><div class="eyebrow">Run overview · ${esc(r.route||'unknown route')}</div><h2>${esc(r.goal||r.task_id)}</h2><div class="muted">${esc(r.run_id)} · task ${esc(r.task_id)}</div></div><button class="button" onclick="window.open('/api/runs/${r.run_id}/export')">Export evidence</button></div><div class="stats"><div class="stat"><b class="${s.final_status}">${esc(s.final_status||'running')}</b><span class="muted">run status</span></div><div class="stat"><b>${durationLabel(r)}</b><span class="muted">wall time</span></div><div class="stat"><b>${s.event_count||0}</b><span class="muted">events</span></div><div class="stat"><b>${s.tool_called_count||0}</b><span class="muted">tool calls</span></div><div class="stat"><b>${esc(s.verification_status||'not_started')}</b><span class="muted">latest verification</span></div></div><div class="tabs"><button class="tab ${mode==='trace'?'active':''}" data-mode="trace">Trace tree</button><button class="tab ${mode==='trajectory'?'active':''}" data-mode="trajectory">Trajectory ledger</button><button class="tab ${mode==='raw'?'active':''}" data-mode="raw">Raw events</button></div>${mode==='trace'?renderTrace(d):mode==='raw'?renderRaw(d):renderTrajectory(d)}<div class="section"><h3>Artifacts and outputs (${d.artifacts.length})</h3>${d.artifacts.map(a=>`<div class="artifact"><span>${esc(a.kind)}</span><span class="muted">${esc(a.path||'')} · ${a.bytes||0} bytes</span></div>`).join('')||'<div class="muted">No artifacts recorded</div>'}</div>`;document.querySelectorAll('[data-mode]').forEach(x=>x.onclick=()=>{mode=x.dataset.mode;renderDetail()});document.querySelectorAll('[data-seq]').forEach(x=>x.onclick=()=>{selectedSeq=Number(x.dataset.seq);renderDetail()})}
['q','status','verify'].forEach(id=>$('#'+id).oninput=renderRuns);fetch('/api/runs').then(r=>r.json()).then(x=>{all=x;renderRuns()});
</script></body></html>'''


def _dump(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def create_handler(reader: EvidenceReader):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, value: Any, status: int = 200, content_type: str = "application/json") -> None:
            body = value if isinstance(value, bytes) else (json.dumps(value, ensure_ascii=False).encode() if content_type == "application/json" else str(value).encode())
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                return self._send(INDEX_HTML, content_type="text/html")
            if path == "/api/runs":
                return self._send([_dump(x) for x in reader.list_runs()])
            parts = PurePosixPath(path).parts
            if len(parts) >= 4 and parts[1] == "api" and parts[2] == "runs":
                run_id = parts[3]
                replay = reader.replay(run_id)
                if replay is None:
                    return self._send({"error": "run not found"}, 404)
                if len(parts) == 5 and parts[4] == "export":
                    return self._send(_dump(replay))
                return self._send(
                    {
                        "run": _dump(replay["run"]),
                        "summary": _dump(replay["summary"]),
                        "events": [_dump(x) for x in replay["events"]],
                        "artifacts": [_dump(x) for x in replay["artifacts"]],
                    }
                )
            self._send({"error": "not found"}, 404)

        def log_message(self, *_: Any) -> None:
            pass
    return Handler


def serve(data_dir: Any, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), create_handler(EvidenceReader(EvidenceStore(data_dir))))
    print(f"Evidence Viewer: http://{host}:{port}")
    server.serve_forever()
