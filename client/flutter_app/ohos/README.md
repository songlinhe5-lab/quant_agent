# HarmonyOS NEXT (`ohos/`)

> CLI-06 · Quant Agent Flutter 薄客户端鸿蒙工程占位。  
> 正式工程用 **华为 flutter-harmonyos Fork** 生成，勿用标准 Flutter 的 `flutter create` 期望直接出 OHOS。

## 生成方式

```bash
# 使用华为发行版 Flutter SDK（示例路径）
export PATH="$HOME/flutter-harmonyos/bin:$PATH"
cd client/flutter_app
flutter create --platforms=ohos .
```

构建时强制标记鸿蒙（心跳 / Push 选型）：

```bash
flutter run --dart-define=HARMONYOS=true
```

## MethodChannel 契约（须与 ArkTS 插件一致）

### HMS Push — `com.quantagent/hms_push`

| Method | 返回 | 说明 |
|:---|:---|:---|
| `isAvailable` | `bool` | Push Kit 是否可用 |
| `getToken` | `String?` | 设备推送 Token |
| `deleteToken` | void | 注销 |
| `getInitialMessage` | `Map?` | 冷启动点击的告警 payload（docs/18） |

EventChannel `com.quantagent/hms_push/events`：前台/后台 data message → JSON Map（含 `event_id` / `ui_hint`）。

### HMS Account — `com.quantagent/hms_auth`

| Method | 返回 | 说明 |
|:---|:---|:---|
| `isAvailable` | `bool` | Account Kit 可用 |
| `signIn` | `Map` | `{authorizationCode, openId?, unionId?, displayName?}` |
| `signOut` | void | 退出华为账号会话 |

Dart 侧换票：`POST /api/v1/auth/hms`（后端未就绪时客户端会提示失败）。

## 约束

- **禁止**在 HarmonyOS 使用 FCM / Firebase Push（华为市场上架会驳回）。
- Token 仍走 `AuthTokenStore`（Secure Storage / HMS Keystore）。
- Feature 层不得直接 `MethodChannel`；只经 `platform/harmonyos/` → Infrastructure Adapter → Port。
