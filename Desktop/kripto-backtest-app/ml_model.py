import xgboost as xgb
import pandas as pd

class SignalML:
    def __init__(self):
        self.model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            use_label_encoder=False,
            eval_metric='mlogloss',
            verbosity=0
        )

    def train(self, X, y):
        self.model.fit(X, y)

    def predict_signals(self, X):
        preds = self.model.predict(X)
        return pd.Series(preds, index=X.index)

    def feature_importance(self):
        importance = self.model.feature_importances_
        features = self.model.get_booster().feature_names
        fi = pd.Series(importance, index=features).sort_values(ascending=False)
        return fi
