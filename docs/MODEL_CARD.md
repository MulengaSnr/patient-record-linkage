# Model card: _model name_

_Based on Mitchell et al. (2019), "Model Cards for Model Reporting". Delete this file if the project has no predictive model._

## Model details
- **Type:** _e.g. XGBoost binary classifier_
- **Version:** _git tag / MLflow run ID_
- **Owner:** Enock Mulenga
- **Date:** _YYYY-MM-DD_

## Intended use
- **Primary use:** _who uses the output, for what decision_
- **Out of scope:** _uses it must not be put to_

## Training and evaluation data
_Dataset, time period, split strategy, known sampling biases._

## Metrics
_Primary metric and why it fits the decision; threshold choice; calibration._

| Metric | Test set | Baseline |
|---|---|---|
| | | |

## Subgroup performance (fairness)
| Group | n | _Metric_ | Gap vs overall |
|---|---|---|---|
| | | | |

## Explainability
_Global drivers (SHAP summary), example local explanations._

## Ethical considerations and UK GDPR
_Personal / special-category data? (Health data is special category under UK GDPR Art. 9.) Automated decision-making (Art. 22)? Human-in-the-loop design?_

## Limitations and risks
-

## Monitoring
_What drift / performance signals would trigger retraining._
