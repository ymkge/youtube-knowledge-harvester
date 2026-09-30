---
name: run-tests
description: Run test suite and check code compilation for YouTube Knowledge Harvester.
---

# Run Tests Skill

このスキルは、YouTube Knowledge Harvester のコードベースの検証や単体テストを一括実行する手順を定義します。

## 実行手順

1. 構文チェック:
   ```bash
   python3 -m py_compile app.py core/extractor.py core/summarizer.py core/exporter.py
   ```

2. ユニットテストの実行:
   ```bash
   python3 -m unittest discover tests
   ```

3. 結果の確認:
   - 全テストが `OK` で終了することを確認してください。
