# RBAC 权限矩阵

> 依据：`backend/app/rbac.py` 的 `require_role()` 与 19 个 router 上的依赖声明（本轮已把全部 62 处写接口挂上角色依赖）。
> 角色等级：`viewer(1) < operator(2) < admin(3) < superadmin(4)`，判定为「达到最低等级即可」。

## 一、角色定义

| 角色 | 定位 | 典型使用者 |
|---|---|---|
| `superadmin` | 最高权限，含管理员账号治理 | 平台所有者 / 交付负责人 |
| `admin` | 管理业务与操作员账号，**不能管理 admin/superadmin** | 运维负责人 |
| `operator` | 日常设备操作（建机、控制、批量、脚本、任务、文件） | 运营人员 |
| `viewer` | 只读：看板、设备列表、详情、投屏、日志、报表 | 观察者 / 甲方验收 |

## 二、权限矩阵

图例：✅ 允许；❌ 403；— 不涉及。

| 资源 \ 操作 | 读（GET） | 写（POST/PATCH/DELETE） | 管理（用户/审计/同步） |
|---|---|---|---|
| 设备 `devices`（列表/详情/快照查看） | viewer ✅ | operator ✅ | admin ✅ |
| 设备生命周期（建/改/删/启停/新机/快照创建与恢复） | viewer ✅（只读子集） | operator ✅ | admin ✅ |
| 单机控制 `control`（点按/滑动/输入/按键/装 APK/开网页/显示/输入法/scrcpy） | viewer ✅ | operator ✅ | admin ✅ |
| 批量控制 `batch`（开网页/点按/滑动/输入/按键/装 APK） | viewer ✅ | operator ✅ | admin ✅ |
| 脚本 `scripts`（列表/详情/导出） | viewer ✅ | operator ✅（建/改/删/回放/导入） | admin ✅ |
| 任务 `tasks`（列表） | viewer ✅ | operator ✅（建/改/删/立即执行/启停） | admin ✅ |
| 分组 `groups`（树/成员） | viewer ✅ | operator ✅（建/改名/删/移动设备） | admin ✅ |
| 应用 `apps`（已装列表） | viewer ✅ | operator ✅（启动/强停/清理/卸载/安装/批量） | admin ✅ |
| 皮肤 `skin` | viewer ✅ | operator ✅（单机/批量换肤） | admin ✅ |
| 文件 `files`（浏览/下载） | viewer ✅ | operator ✅（上传/删除） | admin ✅ |
| 日志 `logs` / 告警 `alerts` / 报表 `reports` / 看板 | viewer ✅ | — | admin ✅ |
| 用户 `users` | admin ✅ | admin ✅（operator/viewer）；superadmin ✅（含 admin） | 仅 admin 起 |
| 审计 `audit` | admin ✅ | —（只读） | 仅 admin 起 |
| 同步配置 `sync` | — | — | 仅 superadmin ✅（本轮改为 admin 起，见下方差异） |
| 自助接口 `/users/me`、`/users/me/password` | 任何已登录用户 ✅ | 任何已登录用户 ✅（仅限自己） | — |

## 三、superadmin 与 admin 的实际差异（以代码为准）

| 能力 | superadmin | admin | 依据 |
|---|---|---|---|
| 查看用户列表 / 审计 | ✅ | ✅ | `routers/users.py`、`routers/audit.py` 路由级 admin 依赖 |
| 创建 `operator` / `viewer` | ✅ | ✅ | `create_user`：目标等级 < 操作者等级 |
| 创建 `admin` / `superadmin` | ✅ | ❌ 400 | `create_user`：目标等级 ≥ 操作者等级直接拒绝 |
| 修改/删除 `admin` / `superadmin` | ✅ | ❌ 400 | `update_user` / `delete_user` 同级保护 |
| 修改自己的角色（降级） | ❌ 400 | ❌ 400 | 禁止自我降级，避免把自己锁在外面 |
| 触发数据同步 `/api/sync/run` | ✅ | ✅ | `sync.py` 本轮统一为 `require_admin` |

**结论**：业务权限上 `superadmin` 目前**仅比 `admin` 多「管理员账号治理」一项**；两者都能进用户管理页，但 admin 看不到/动不了同级与上级账号。
若后续要引入「审计只读管理员」「租户隔离」等，需要再拆分角色（已记入 `docs/改造计划.md` 待收敛项）。

## 四、执行位置与前端配合

1. **后端为准**：所有写接口的 `@router.*` 上都有 `dependencies=[Depends(require_operator)]`（用户/审计/同步为 admin）。漏配会在 pytest 的 4 角色用例里暴露。
2. **自助改密**：`/api/users/me/password` 挂在独立的 `users.me_router` 上，不带 admin 依赖；改密只改 token 所属用户，不接受 `user_id` 参数，因此无法改他人。
3. **前端只做体验收敛**：`frontend/src/stores/auth.js` 暴露 `role` 与 `can('operator'|'admin')`；
   设备/批量/控制/脚本/任务/应用/文件/分组页面对无权限按钮做隐藏或禁用；
   `Users`、`Audit` 路由由 `router/index.js` 的 `meta.minRole` 白名单拦截。即使绕过 UI，后端仍返回 403。

## 五、自检

```bash
# 后端：4 角色 × 读写接口
cd backend && python -m pytest tests/test_rbac.py -q

# 统计写接口依赖数量（应为 62 处左右）
grep -rn "require_operator\|require_admin" backend/app/routers backend/app/sync.py | wc -l
```
