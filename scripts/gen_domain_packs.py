"""One-off generator for the seed domain glossary packs.

Not part of the runtime -- run manually when adding/editing a pack, then
delete or extend as needed. Writes via csv.writer so multi-word notes with
commas are quoted correctly (see the CBRN row bug this avoided in
dictionary.csv).
"""

import csv
from pathlib import Path

PACKS_DIR = Path(__file__).resolve().parent.parent / "dictionaries" / "domains"

MACHINE_LEARNING: list[tuple[str, str, str]] = [
    ("AGI", "AGI", ""),
    ("AIME", "AIME", "Mathematics benchmark"),
    ("Anaconda", "Anaconda", ""),
    ("application programming interface", "API", ""),
    ("architecture efficiency", "アーキテクチャ効率", "効率性の6側面"),
    ("attention", "アテンション", ""),
    ("automatic differentiation", "自動微分", ""),
    ("backpropagation", "誤差逆伝播", ""),
    ("bag of words", "Bag of Words", ""),
    ("bagging", "バギング", ""),
    ("basket data", "バスケットデータ", ""),
    ("batch learning", "バッチ学習", ""),
    ("BERT", "BERT", ""),
    ("bias", "バイアス", ""),
    ("Block Verification", "ブロック検証", ""),
    ("boosting", "ブースティング", ""),
    ("breakeven", "損益分岐点", "エネルギー的な話だと投入したエネルギーと"),
    ("budget efficiency", "予算効率", "効率性の6側面"),
    ("cascade model", "カスケードモデル", ""),
    ("causality", "因果性", ""),
    ("CBRN", "CBRN", "Chemical, Biological, Radiological, Nuclear risks"),
    ("chain of thought", "Chain of Thought", ""),
    ("CIFAR-10", "CIFAR-10", ""),
    ("CIFAR-100", "CIFAR-100", ""),
    ("classification", "分類", ""),
    ("clustering", "クラスタリング", ""),
    ("CNN", "CNN", ""),
    ("dense pretrained model", "密な事前学習済みモデル", ""),
    ("dimensionality reduction", "次元削減", ""),
    ("domain adaptation", "ドメイン適応", ""),
    ("downstream adaptation", "下流タスクへの適応", ""),
    ("dropout", "ドロップアウト", ""),
    ("dummy variable", "ダミー変数", ""),
    ("efficiency spectrum", "効率性のスペクトル", "論文タイトル"),
    ("efficient attention", "効率的な注意機構", "アーキテクチャ"),
    ("efficient reasoning model", "効率的な推論モデル", ""),
    (
        "rotary positional embeddings",
        "Rotary Positional Embeddings (RoPE)",
        "アーキテクチャ",
    ),
    ("rectified linear unit", "Rectified Linear Unit (ReLU)", ""),
    ("recurrent neural network", "再帰型ニューラルネットワーク (RNN)", ""),
    ("principal component analysis", "主成分分析 (PCA)", ""),
    ("mixture of experts", "専門家混合モデル (MoE)", "アーキテクチャ"),
    ("language model", "言語モデル", ""),
    ("RLHF", "RLHF", ""),
    ("fine-tuning", "ファインチューニング", ""),
    ("inference", "推論", ""),
    ("latency", "レイテンシー", ""),
    ("throughput", "スループット", ""),
    ("transformer", "トランスフォーマー", "モデルアーキテクチャ"),
    ("neural network", "ニューラルネットワーク", ""),
    ("deep learning", "深層学習", ""),
    ("machine learning", "機械学習", ""),
    ("overfitting", "過学習", ""),
    ("regularization", "正則化", ""),
    ("gradient descent", "勾配降下法", ""),
    ("embedding", "埋め込み", ""),
    ("tokenization", "トークン化", ""),
    ("reinforcement learning", "強化学習", ""),
    ("supervised learning", "教師あり学習", ""),
    ("unsupervised learning", "教師なし学習", ""),
]

PARTICLE_PHYSICS: list[tuple[str, str, str]] = [
    ("quark", "クォーク", ""),
    ("lepton", "レプトン", ""),
    ("boson", "ボゾン", ""),
    ("fermion", "フェルミオン", ""),
    ("Higgs boson", "ヒッグス粒子", ""),
    ("Higgs field", "ヒッグス場", ""),
    ("gluon", "グルーオン", ""),
    ("photon", "光子", ""),
    ("neutrino", "ニュートリノ", ""),
    ("electron", "電子", ""),
    ("muon", "ミューオン", ""),
    ("tau lepton", "タウ粒子", ""),
    ("hadron", "ハドロン", ""),
    ("baryon", "バリオン", ""),
    ("meson", "中間子", ""),
    ("proton", "陽子", ""),
    ("neutron", "中性子", ""),
    ("antiparticle", "反粒子", ""),
    ("antimatter", "反物質", ""),
    ("spin", "スピン", ""),
    ("charge conjugation", "荷電共役", ""),
    ("parity violation", "パリティ対称性の破れ", ""),
    ("CP violation", "CP対称性の破れ", ""),
    ("Standard Model", "標準模型", "素粒子物理学の標準理論"),
    ("quantum chromodynamics", "量子色力学", "QCD"),
    ("quantum electrodynamics", "量子電磁力学", "QED"),
    ("gauge symmetry", "ゲージ対称性", ""),
    ("gauge boson", "ゲージ粒子", ""),
    ("strong force", "強い相互作用", "強い力"),
    ("weak force", "弱い相互作用", "弱い力"),
    ("electroweak interaction", "電弱相互作用", ""),
    ("confinement", "閉じ込め", "クォークの閉じ込め"),
    ("asymptotic freedom", "漸近的自由性", ""),
    ("color charge", "色荷", ""),
    ("Feynman diagram", "ファインマン図", ""),
    ("cross section", "断面積", ""),
    ("luminosity", "ルミノシティ", "衝突型加速器の輝度"),
    ("decay channel", "崩壊チャンネル", ""),
    ("branching ratio", "分岐比", ""),
    ("particle accelerator", "粒子加速器", ""),
    ("collider", "コライダー", "衝突型加速器"),
    ("Large Hadron Collider", "大型ハドロン衝突型加速器", "LHC"),
    ("detector", "検出器", ""),
    ("calorimeter", "カロリメータ", ""),
    ("dark matter", "ダークマター", "暗黒物質"),
    ("dark energy", "ダークエネルギー", ""),
    ("supersymmetry", "超対称性", ""),
    ("string theory", "超弦理論", ""),
    ("vacuum expectation value", "真空期待値", ""),
    ("symmetry breaking", "対称性の破れ", ""),
    ("spontaneous symmetry breaking", "自発的対称性の破れ", ""),
    ("renormalization", "くりこみ", ""),
    ("Lagrangian", "ラグランジアン", ""),
    ("conservation law", "保存則", ""),
    ("angular momentum", "角運動量", ""),
    ("four-momentum", "四元運動量", ""),
    ("Lorentz invariance", "ローレンツ不変性", ""),
    ("quantum field theory", "場の量子論", ""),
    ("vacuum", "真空", ""),
    ("annihilation", "対消滅", ""),
    ("pair production", "対生成", ""),
]

PACKS = {
    "machine_learning": MACHINE_LEARNING,
    "particle_physics": PARTICLE_PHYSICS,
}


def main() -> None:
    PACKS_DIR.mkdir(parents=True, exist_ok=True)
    for name, entries in PACKS.items():
        path = PACKS_DIR / f"{name}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["source_term", "target_term", "notes"])
            writer.writerows(entries)
        print(f"Wrote {path} ({len(entries)} entries)")


if __name__ == "__main__":
    main()
