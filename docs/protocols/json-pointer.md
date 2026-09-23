# 扩展 JSON Pointer 规范

用于从 LLM 响应中提取正文、推理内容与用量字段。基础行为兼容
[RFC 6901](https://www.rfc-editor.org/rfc/rfc6901)，并**仅增加一个扩展**：数组负索引。

## 1. 语法

```text
pointer = "" | *( "/" reference-token )
```

- `""` 指向整个文档；
- `reference-token` 中的 `~1` 解码为 `/`，`~0` 解码为 `~`；
- 其他以 `~` 开头但非 `~0` / `~1` 的序列为非法转义。

## 2. 数组下标

| 写法 | 含义 | 示例 |
|---|---|---|
| `0` | 第一个元素 | `/choices/0/message/content` |
| `-1` | 最后一个元素 | `/choices/-1/message/content` |
| `-2` | 倒数第二个元素 | `/content/-2/text` |

## 3. 定案语义

| 情形 | 行为 |
|---|---|
| `""` | 返回整个文档 |
| `-0` | **非法**，报 `PointerError` |
| 单独的 `-` | **非法**（RFC 6901 中 `-` 仅用于写入语义，本项目只做读取） |
| 负索引绝对值超过数组长度 | 报 `PointerError` |
| 对非数组使用数字或 `-N` 下标 | 报 `PointerError` |
| 字典键不存在 | 报 `PointerError` |
| 对列表使用非数字 token | 报 `PointerError` |
| 非法转义（`~` 后非 0/1） | 报 `PointerError` |
| 路径中途遇到标量（如对字符串取子键） | 报 `PointerError` |

## 4. 示例

给定响应：

```json
{
  "choices": [
    {"message": {"content": "Hello"}},
    {"message": {"content": "World"}}
  ],
  "usage": {"total_tokens": 42}
}
```

| 指针 | 结果 |
|---|---|
| `/choices/0/message/content` | `"Hello"` |
| `/choices/-1/message/content` | `"World"` |
| `/usage/total_tokens` | `42` |
| `/choices/2/message` | `PointerError`（越界） |
| `/choices/-3/message` | `PointerError`（越界） |
| `/choices/-0/message` | `PointerError`（非法写法） |

## 5. 实现要求

- 纯 Python，不依赖 Qt / HTTP；
- 独立完整的单元测试，覆盖上表全部情形；
- 解析与求值分离：`parse_pointer` 只做词法解析与转义，`resolve_pointer` 负责求值。
