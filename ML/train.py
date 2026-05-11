import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score
import joblib

def train_model(data_path: str):
    df = pd.read_csv(data_path)
    
    # 1. 准备特征
    # 去除不需要的列
    drop_cols = ["timestamp", "direction", "label"]
    X = df.drop(columns=[col for col in drop_cols if col in df.columns])
    y = df["label"]
    
    print(f"特征列表: {list(X.columns)}")
    
    # 2. 划分训练集和测试集
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    
    # 3. 训练随机森林模型
    # 我们不再过度惩罚假突破，而是追求更平衡的预测能力
    model = RandomForestClassifier(
        n_estimators=200,      # 增加树的数量
        max_depth=12,          # 增加深度，捕捉更复杂的PA组合
        min_samples_leaf=5,    # 保证泛化能力
        class_weight="balanced", # 自动平衡 0 和 1 的比例
        random_state=42
    )
    model.fit(X_train, y_train)
    
    # 4. 评估
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]
    
    print("\n模型评估报告:")
    print(classification_report(y_test, y_pred))
    print(f"ROC AUC Score: {roc_auc_score(y_test, y_prob):.4f}")
    
    # 5. 特征重要性
    importances = pd.DataFrame({
        "feature": X.columns,
        "importance": model.feature_importances_
    }).sort_values("importance", ascending=False)
    print("\n特征重要性排名:")
    print(importances.head(10))
    
    # 6. 保存模型
    model_dir = Path(data_path).parents[1] / "models"
    model_dir.mkdir(exist_ok=True)
    model_path = model_dir / "breakout_classifier.joblib"
    joblib.dump(model, model_path)
    # 同时保存特征名，确保后续推理时顺序一致
    feature_names_path = model_dir / "feature_names.joblib"
    joblib.dump(list(X.columns), feature_names_path)
    
    print(f"\n模型已保存至: {model_path}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str, required=True)
    args = parser.parse_args()
    
    train_model(args.data)
