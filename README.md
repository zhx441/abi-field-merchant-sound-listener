# 暗区战地商人 · 听声识物

## 下载与使用

1. [下载 Windows 版（.exe）](https://github.com/zhx441/abi-field-merchant-sound-listener/releases/download/v10/MerchantSoundListener_CN_v10.exe)，双击运行。
2. 在「游戏播放设备」中选择游戏声音输出的设备，点击「开始监听」，然后拖动战地商人的神秘货物。
3. 按货物占格筛选候选物品，点击「▶ 拾起」或「▶ 放下」试听参考音效。

窗口置顶默认开启，可在主界面取消。游戏使用独占全屏时，建议切换到无边框窗口模式。

本工具由社区维护，未获得游戏官方的兼容性确认。游戏内使用受 [《暗区突围：无限》用户协议](https://store.steampowered.com/eula/2073620_eula_0) 约束。

**匹配分和音效峰值强度都不是掉落概率。** 多件物品可能共用同一声音组，仅靠音频无法区分组内物品。参考表包含 38 组音效及 189 件物品；非线性节点探测器不在当前参考表中。

## 从源码运行

需要 Windows 和 Python 3.11+。

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe merchant_listener.py
```

程序使用 `catalog.json`、`reference/` 和 `icons/`。`reference/` 含 76 段参考音效，`icons/` 含候选物品图标。程序不读取游戏内存，也不上传录音。

## 测试范围

`docs/逐组召回测试报告.md` 列出了 38 组音效各自的拾起、放下测试。每段参考音效在四种模拟背景下测试，共 304 次；安静、低频音乐和宽带杂音场景各为 76/76，高频音乐为 74/76。这是参考音效混音测试，不代表真实游戏环境的召回率。

## 数据来源

音效、物品分组及类别来自社区维护的 [ABI Builder 战地商人页面](https://abibuilder.com/merchant)，中文名称来自 [abi-assets 游戏本地化数据](https://github.com/hexaov91/abi-assets/tree/main/localization/game)，图标来自 ABI Builder 的物品图片资源。类别标签是对参考表英文类别的中文翻译。参考表版本：`1.0.0.151.4`。本项目与游戏官方及上述社区项目无关联。

## 开源协议

本项目编写的程序代码与文档采用 [MIT 协议](LICENSE)。游戏音效、物品图片和游戏数据不属于 MIT 授权范围，详见 [第三方资源说明](THIRD_PARTY_ASSETS.md)。
