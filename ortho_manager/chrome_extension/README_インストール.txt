OrthoManager Chrome連携拡張

目的
「同じタブを更新」を選んだ時、OrthoManager専用のGoogleマップタブを再利用します。

導入方法
1. Chromeで chrome://extensions/ を開きます。
2. 右上の「デベロッパー モード」をオンにします。
3. 「パッケージ化されていない拡張機能を読み込む」を押します。
4. この chrome_extension フォルダを選択します。

使い方
1. OrthoManagerの「ツール」→「背景地図・Web地図」を開きます。
2. 「同じタブを更新」を選びます。
3. 「現在の表示をGoogleマップで開く」を押します。
最初の1回はGoogleマップタブを作り、2回目以降はそのタブを更新します。

権限
Googleマップのタブを更新するため、tabs、webNavigation、storageと
https://www.google.com/maps/* へのアクセスだけを使います。
