# Hermes 分阶段工程实现

本功能依次执行规划、实现和主机验证，不是 MoA，也不是提供商故障回退。
启用 `implementation_router` 插件，然后在现有辅助模型选择器中配置 `engineering_planner`、`engineering_worker` 和 `engineering_reviewer`。可以选择已配置提供商支持的任意模型；不可用时停止，不暗中更换模型。
在插件设置中指定不含秘密的 `source_paths`、受保护验收测试 `protected_paths`、预先准备的镜像摘要及固定验证命令 `checks`。调用 `/engineer {"workspace":"sample","task":"按TDD实现所需修改"}`。
凭据和推理客户端只保留在父 Hermes 主机中。子孙进程在新的受检查 Docker 环境内运行，不继承主机凭据挂载、环境变量或网络。Windows 主机同样需要 Linux Docker 引擎，不允许退回普通本地 shell。
成功后返回经过验证的工作区副本，不直接修改原始检出目录，也不自动合并 PR。必须查看最终提交的 CI 和原生验收结果；模拟推理测试不代表真实账户可用性。
空环境变量不等于操作系统隔离。主机、Docker 守护进程、镜像和受信任插件属于信任基础。检查输入源码中的嵌入秘密。遗留 lease 需要操作者调查后恢复，不自动重放完成情况不明的任务。

<!-- routing-not-moa -->
<!-- credentials-host-only -->
<!-- native-adapter-requirements -->
<!-- not-os-sandbox -->

[Agent protocol](../AGENT_PROTOCOL.md)

每个阶段的推理设置按角色固定，并在父进程的请求边界验证 medium/medium/high，而不是依据界面标签推断。阻止执行的结果可包含不泄露凭据的固定诊断代码。保留 lease 和 journal；诊断不代表获得重放许可。
