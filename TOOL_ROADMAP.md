# KAI AGENT Tool 扩展清单

## 已实现（9 个）

| Tool | 文件 | 功能 |
|------|------|------|
| `bash` | `builtin/bash.py` | 执行终端命令 |
| `read_file` | `builtin/file_reader.py` | 读取文件内容 |
| `write_file` | `builtin/file_writer.py` | 写入/创建文件 |
| `web_search` | `builtin/web_search.py` | 搜索互联网（占位） |
| `python_repl` | `builtin/python_repl.py` | 执行 Python 代码 |
| `file_deleter` | `builtin/file_deleter.py` | 删除文件 |
| `system_info` | `builtin/system_info.py` | 一键获取系统概况 |
| `process_manager` | `builtin/process_manager.py` | 查看/管理运行中的进程 |
| `read_document` | `builtin/read_document.py` | 读取 PDF / Word / Excel 文档 |

---

## 待实现清单

### 一、网络类

#### 1. `http_request`
发起 HTTP 请求，替代手动 curl。

```
GET https://api.example.com/data
POST https://api.example.com/submit  body={"key":"val"}
```

- 参数：method, url, headers?, body?, timeout?
- 权限：NETWORK
- 实现：`urllib.request` 或 `httpx`
- 注意：禁止请求内网敏感地址

#### 2. `web_search` 真实化
目前是占位，接入真实搜索引擎。

- 方案 A：SERPAPI / Serper.dev（付费，效果好）
- 方案 B：DuckDuckGo 免费 API（`duckduckgo_search` 库）
- 方案 C：Bing Web Search API（Azure，有免费额度）
- 参数：query, num_results?
- 权限：NETWORK

---

### 二、文件类

#### 4. `find_files`
按名称、类型、大小查找文件。

```
find *.py              → 找所有 Python 文件
find report*           → 找 report 开头的文件
find *.log --large     → 找大于 10MB 的日志
```

- 参数：pattern, directory?, min_size?, max_size?, recursive?
- 权限：READ_ONLY
- 实现：`glob` + `os.walk`

#### 5. `dir_tree`
以树形结构展示目录。

```
项目根/
├── src/
│   ├── main.py
│   └── utils.py
├── tests/
└── README.md
```

- 参数：directory?, max_depth?
- 权限：READ_ONLY
- 实现：`os.walk` + 格式化输出

#### 6. `compare_files`
对比两个文件的差异（diff）。

- 参数：file1, file2, context_lines?
- 权限：READ_ONLY
- 实现：`difflib.unified_diff`

#### 7. `zip_files`
打包/解压文件。

- 参数：action(compress/extract), source, destination?, format?
- 权限：READ_WRITE
- 实现：`zipfile` / `tarfile`

---

### 三、系统类

#### 8. `system_info`
一键获取系统概况（OS、CPU、内存、磁盘、网络）。

- 参数：info_type?(cpu/memory/disk/network/all)
- 权限：READ_ONLY
- 实现：`psutil` 库
- 比手动敲 bash 更结构化

#### 9. `process_manager`
查看/管理运行中的进程。

- 参数：action(list/kill/info), pid?, name?
- 权限：SHELL（kill 操作需要 DESTRUCTIVE）
- 实现：`psutil`
- kill 操作设置 requires_confirmation=True

#### 10. `clipboard`
读写系统剪贴板。

- 参数：action(read/write), content?
- 权限：READ_ONLY（读）/ READ_WRITE（写）
- 实现：`pyperclip` 库
- 注意：写操作需要确认

#### 11. `env_manager`
查看/设置环境变量。

- 参数：action(get/set/list), key?, value?
- 权限：READ_ONLY（get）/ READ_WRITE（set）
- 实现：`os.environ`
- set 仅对当前进程生效

---

### 四、数据处理类

#### 12. `json_tool`
格式化、查询、校验 JSON 数据。

- 参数：action(format/query/validate), data?, jq_filter?
- 权限：READ_ONLY
- 实现：`json` 模块

#### 13. `csv_tool`
读取和简单处理 CSV 文件。

- 参数：file_path, action(read/stats/head), rows?
- 权限：READ_ONLY
- 实现：`csv` 模块或 `pandas`

#### 14. `calculator`
高精度数学计算（比 python_repl 更安全）。

- 参数：expression, precision?
- 权限：READ_ONLY
- 实现：`decimal` 模块或 `sympy`
- 比 python_repl 安全，不会执行任意代码

---

### 五、开发辅助类

#### 15. `git_tool`
常用 Git 操作的封装。

- 参数：action(status/log/diff/branch/commit), message?, files?
- 权限：SHELL
- commit / push 需要 `requires_confirmation=True`
- 禁止 force push 和 hard reset

#### 16. `code_stats`
统计代码行数、文件数。

- 参数：directory?, language?
- 权限：READ_ONLY
- 实现：遍历文件 + 计数

#### 17. `run_script`
安全运行指定脚本（Python / Shell）。

- 参数：script_path, args?
- 权限：SHELL
- 实现：`subprocess.run`
- 注意：脚本必须在项目目录内

---

### 六、效率类

#### 18. `timer`
设置定时提醒。

```
timer 5分钟后提醒我开会
timer 14:30 休息
```

- 参数：time, message
- 权限：READ_ONLY
- 实现：`threading.Timer`

#### 19. `text_tool`
文本处理（计数、去重、排序、正则替换）。

- 参数：action, text?, pattern?, replacement?
- 权限：READ_ONLY
- 实现：`re` + 字符串操作

#### 20. `translate`
简单翻译（接入翻译 API）。

- 参数：text, target_lang, source_lang?
- 权限：NETWORK
- 实现：`googletrans` 或百度翻译 API

---

## 优先级建议

| 优先级 | Tool | 理由 |
|--------|------|------|
| P0 | `web_search` 真实化 | 占位太久了，搜索是高频需求 |
| P0 | `http_request` | curl 太常用，封装后更安全 |
| P1 | `find_files` + `dir_tree` | 文件操作的自然延伸 |
| P1 | `system_info` | 比手敲 bash 更友好 |
| P1 | `read_document` | 读 PDF/Word 是常见需求 |
| P2 | `clipboard` | 方便传递数据 |
| P2 | `git_tool` | 开发者高频 |
| P3 | 其余 | 按需实现 |
