"""
AI Weekly Digest — Decoupled pipeline steps.
AI 周刊摘要 — 解耦的流水线步骤。

Each step is an independent function that:
每个步骤都是独立的函数：
- Reads input from disk (previous step's artifact) | 从磁盘读取输入（上一步的产物）
- Processes the data                                | 处理数据
- Writes output to disk                            | 将输出写入磁盘
- Returns a result dict for the orchestrator        | 返回结果字典给编排器

Steps communicate ONLY through filesystem artifacts (JSON/HTML files).
步骤之间仅通过文件系统产物（JSON/HTML文件）通信。

Designed to be easily wrapped as independent Agents in the future.
设计为未来可以轻松封装为独立的 Agent。
"""
