"""脚本录制→跨设备回放（D13 / demo 验收 §8）。

步骤模型对齐 Airtest .air 的抽象：open_url / tap / swipe / text / key / wait，
并新增逻辑控制 loop（循环执行嵌套步骤）。
录制：前端把用户在单机操控页的动作序列提交为一个脚本。
回放：把脚本步骤在选中的多台设备上依次执行，生成逐设备、逐步骤的报告。

可视化编辑（GM-201/202/205, 7.4.2/7.4.4）新增：
- 模板库：GET /scripts/templates、POST /scripts/from-template
- 导入导出：GET /scripts/{id}/export、POST /scripts/import
- 在线编辑：PUT /scripts/{id}
"""
from __future__ import annotations

import asyncio
import copy

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..rbac import require_operator
from ..database import get_db
from ..models import Device, Script, ScriptRun
from ..schemas import ScriptCreate, ScriptOut, ScriptRunOut, ScriptRunRequest
from ..script_templates import TEMPLATES
from .. import services
from ..ws_manager import manager

router = APIRouter(prefix="/scripts", tags=["scripts"], dependencies=[Depends(get_current_user)])

# 逻辑控制约束（防止误配置拖垮回放）
VALID_ACTIONS = {"open_url", "tap", "swipe", "text", "key", "wait", "loop"}
MAX_LOOP_COUNT = 100
MAX_LOOP_DEPTH = 3
MAX_WAIT_SECONDS = 30


class FromTemplateRequest(BaseModel):
    template_index: int


def _validate_steps(steps: object, depth: int = 0) -> None:
    """校验步骤列表：动作必须已知，loop 嵌套不超过 MAX_LOOP_DEPTH 层。"""
    if not isinstance(steps, list):
        raise HTTPException(400, "步骤必须是列表")
    for step in steps:
        if not isinstance(step, dict):
            raise HTTPException(400, "每个步骤必须是对象 {action, params}")
        action = step.get("action")
        if action not in VALID_ACTIONS:
            raise HTTPException(400, f"未知动作: {action}")
        if action == "loop":
            if depth + 1 > MAX_LOOP_DEPTH:
                raise HTTPException(400, f"循环嵌套深度不能超过 {MAX_LOOP_DEPTH} 层")
            params = step.get("params") or {}
            _validate_steps(params.get("steps") or [], depth + 1)


@router.get("", response_model=list[ScriptOut])
async def list_scripts(db: AsyncSession = Depends(get_db)) -> list[Script]:
    return list((await db.execute(select(Script).order_by(Script.id))).scalars().all())


@router.post("", response_model=ScriptOut, dependencies=[Depends(require_operator)])
async def create_script(body: ScriptCreate, db: AsyncSession = Depends(get_db)) -> Script:
    script = Script(
        name=body.name,
        description=body.description,
        steps=[s.model_dump() for s in body.steps],
    )
    db.add(script)
    await db.commit()
    await db.refresh(script)
    return script


# --------- 模板库（7.4.4）---------
# 注意：/templates 必须注册在 /{script_id} 之前，否则会被参数路由拦截。
@router.get("/templates")
async def list_templates() -> list[dict]:
    """内置脚本模板库（只读种子）。"""
    return TEMPLATES


@router.post("/from-template", response_model=ScriptOut, dependencies=[Depends(require_operator)])
async def create_from_template(
    body: FromTemplateRequest, db: AsyncSession = Depends(get_db)
) -> Script:
    if body.template_index < 0 or body.template_index >= len(TEMPLATES):
        raise HTTPException(404, "模板不存在")
    tpl = TEMPLATES[body.template_index]
    script = Script(
        name=tpl["name"],
        description=tpl.get("description", ""),
        steps=copy.deepcopy(tpl.get("steps", [])),
    )
    db.add(script)
    await db.commit()
    await db.refresh(script)
    return script


# --------- 导入（7.4.4）---------
@router.post("/import", response_model=ScriptOut, dependencies=[Depends(require_operator)])
async def import_script(body: ScriptCreate, db: AsyncSession = Depends(get_db)) -> Script:
    steps = [s.model_dump() for s in body.steps]
    _validate_steps(steps)
    script = Script(name=body.name, description=body.description, steps=steps)
    db.add(script)
    await db.commit()
    await db.refresh(script)
    return script


@router.get("/{script_id}", response_model=ScriptOut)
async def get_script(script_id: int, db: AsyncSession = Depends(get_db)) -> Script:
    script = await db.get(Script, script_id)
    if script is None:
        raise HTTPException(404, "脚本不存在")
    return script


# --------- 导出（7.4.4）---------
@router.get("/{script_id}/export")
async def export_script(script_id: int, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    script = await db.get(Script, script_id)
    if script is None:
        raise HTTPException(404, "脚本不存在")
    payload = {
        "name": script.name,
        "description": script.description,
        "steps": script.steps,
    }
    filename = f"script_{script.id}.json"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------- 在线编辑（可视化编辑器保存）---------
@router.put("/{script_id}", response_model=ScriptOut, dependencies=[Depends(require_operator)])
async def update_script(
    script_id: int, body: ScriptCreate, db: AsyncSession = Depends(get_db)
) -> Script:
    script = await db.get(Script, script_id)
    if script is None:
        raise HTTPException(404, "脚本不存在")
    steps = [s.model_dump() for s in body.steps]
    _validate_steps(steps)
    script.name = body.name
    script.description = body.description
    script.steps = steps
    await db.commit()
    await db.refresh(script)
    return script


@router.delete("/{script_id}", dependencies=[Depends(require_operator)])
async def delete_script(script_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    script = await db.get(Script, script_id)
    if script is None:
        raise HTTPException(404, "脚本不存在")
    await db.delete(script)
    await db.commit()
    return {"ok": True}


async def _exec_loop(device: Device, params: dict, depth: int) -> dict:
    """执行 loop：把嵌套步骤重复 count 次，返回一条汇总记录。

    嵌套步骤内的失败不会中断整个循环，而是累计到汇总里，方便回放报告展示。
    """
    if depth >= MAX_LOOP_DEPTH:
        raise ValueError(f"循环嵌套深度不能超过 {MAX_LOOP_DEPTH} 层")
    try:
        count = int(params.get("count", 1))
    except (TypeError, ValueError):
        count = 1
    count = max(0, min(count, MAX_LOOP_COUNT))
    nested = params.get("steps") or []

    executed = 0
    failed = 0
    errors: list[str] = []
    for _ in range(count):
        for sub in nested:
            executed += 1
            try:
                res = await _exec_step(device, sub, depth + 1)
                if isinstance(res, dict) and res.get("ok") is False:
                    failed += 1
                    if len(errors) < 5:
                        errors.append(f"{sub.get('action')}: 内层 {res.get('failed')} 步失败")
            except Exception as e:  # noqa: BLE001
                failed += 1
                if len(errors) < 5:
                    errors.append(f"{sub.get('action')}: {e}")

    summary = {
        "loop": True,
        "count": count,
        "sub_steps": len(nested),
        "executed": executed,
        "succeeded": executed - failed,
        "failed": failed,
        "ok": failed == 0,
    }
    if errors:
        summary["errors"] = errors
    return summary


async def _exec_step(device: Device, step: dict, depth: int = 0) -> dict | None:
    """执行单个步骤。普通动作返回 None；loop 返回一条汇总 dict。"""
    action = step.get("action")
    p = step.get("params", {})
    if action == "open_url":
        await services.backend.open_url(device, p["url"])
    elif action == "tap":
        await services.backend.tap(device, p["x"], p["y"])
    elif action == "swipe":
        await services.backend.swipe(device, p["x1"], p["y1"], p["x2"], p["y2"], p.get("duration_ms", 300))
    elif action == "text":
        await services.backend.input_text(device, p["text"])
    elif action == "key":
        await services.backend.key(device, p["key"])
    elif action == "wait":
        await asyncio.sleep(min(p.get("seconds", 1), MAX_WAIT_SECONDS))
    elif action == "loop":
        return await _exec_loop(device, p, depth)
    else:
        raise ValueError(f"未知动作: {action}")
    return None


@router.post("/{script_id}/run", response_model=ScriptRunOut, dependencies=[Depends(require_operator)])
async def run_script(script_id: int, body: ScriptRunRequest, db: AsyncSession = Depends(get_db)) -> ScriptRun:
    script = await db.get(Script, script_id)
    if script is None:
        raise HTTPException(404, "脚本不存在")
    devices = list(
        (await db.execute(select(Device).where(Device.id.in_(body.device_ids)))).scalars().all()
    )

    async def _run_on(device: Device) -> dict:
        step_results = []
        ok_all = True
        for step in script.steps:
            try:
                detail = await _exec_step(device, step)
                entry = {"action": step.get("action"), "ok": True}
                if detail:
                    entry.update(detail)
                    if entry.get("ok") is False:
                        ok_all = False
                step_results.append(entry)
            except Exception as e:  # noqa: BLE001
                ok_all = False
                step_results.append({"action": step.get("action"), "ok": False, "error": str(e)})
        return {
            "device_id": device.id,
            "name": device.name,
            "status": "success" if ok_all else "failed",
            "steps": step_results,
        }

    results = await asyncio.gather(*[_run_on(d) for d in devices])
    await db.commit()

    for d in devices:
        await services.broadcast_device(d)

    status = "success" if all(r["status"] == "success" for r in results) else "failed"
    run = ScriptRun(script_id=script.id, status=status, results=list(results))
    db.add(run)
    await db.commit()
    await db.refresh(run)
    await manager.broadcast({"type": "script_done", "run_id": run.id, "status": status})
    return run


@router.get("/runs/{run_id}", response_model=ScriptRunOut)
async def get_run(run_id: int, db: AsyncSession = Depends(get_db)) -> ScriptRun:
    run = await db.get(ScriptRun, run_id)
    if run is None:
        raise HTTPException(404, "运行记录不存在")
    return run
