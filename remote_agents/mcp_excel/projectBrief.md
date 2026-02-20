# Excel MCP Server プロジェクト概要

## プロジェクトの目的
Model Context Protocol (MCP) を使用してMicrosoft Excelファイルの読み書きを行うサーバーを提供する。

## 主な機能
- Excelファイルからのテキストデータの読み取り
- Excelファイルへのテキストデータの書き込み
- ページネーション機能によるデータの効率的な取り扱い

## 対応ファイル形式
- xlsx (Excel book)
- xlsm (Excel macro-enabled book)
- xltx (Excel template)
- xltm (Excel macro-enabled template)

## 技術スタック
- 開発言語: Go
- フレームワーク/ライブラリ:
  - goxcel: Excel操作用ライブラリ
  - その他Go標準ライブラリ

## 要件
- Node.js 20.x 以上（実行環境）

## インストール方法
- NPM経由でのインストール
- Smithery経由でのインストール（Claude Desktop向け）
