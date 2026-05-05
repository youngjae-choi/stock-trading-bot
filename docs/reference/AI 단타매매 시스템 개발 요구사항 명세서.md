본 프로젝트의 목적은 금융 시장의 비정상성(Non-stationary), 비선형성 및 높은 노이즈 수준에 대응하여 수익성 있는 단타매매(Scalping/Day Trading) 기회를 포착하고 실행을 자동화하는 고성능 시스템을 구축하는 데 있습니다. 단순히 가격의 방향성을 예측하는 단계를 넘어, 기술적 분석(Technical Analysis) 전략으로 도출된 매매 신호를 머신러닝(ML) 및 딥러닝(DL) 모델이 2차 필터링하는 하이브리드 아키텍처를 설계합니다. 이를 통해 인간 트레이더의 심리적 편향을 배제하고, 주식 및 암호화폐 시장의 미세 구조(Microstructure)에서 발생하는 비효율성을 수익화합니다.
2. 데이터 획득 및 전처리 (Data Pipeline)
2.1 OpenBB SDK 기반 통합 데이터 수집
표준화 인프라: OpenBB SDK를 활용하여 Yahoo Finance, Alpha Vantage 등 파편화된 데이터 벤더의 출력을 내부 통합 스키마(Standardized Structure)로 정규화합니다.
다중 자산 수집: 주식, 암호화폐(GDAX 등), 거시경제 지표를 통합 수집하여 데이터 정제 시간을 단축하고 알파(Alpha) 발굴에 집중합니다.
2.2 기술적 지표 및 피처 엔지니어링 (Feature Engineering)
OHLCV 데이터를 기반으로 모델 학습에 최적화된 피처를 생성합니다.
추세 및 변동성 지표:
RSI (9-15일), MACD (12-26-9 EMA), 볼린저 밴드 (2 Standard Deviations), SMA, EMA.
DMI (+DI, -DI, DX) 및 ATR (Average True Range).
패턴 식별 (구조적 분리):
Candlestick Patterns (Boolean): Doji, Hammer 등 13가지 주요 패턴을 불리언 타입으로 변환.
Chart Patterns (Geometric): Falling Wedge, Descending Triangle, Symmetrical Triangle 등 기하학적 차트 패턴 피처화.
오더북(Order Book) 미세 구조 피처:
Mid-price (p 
t
​
 ): (b 
t
(1)
​
 +a 
t
(1)
​
 )/2.
Volume-weighted distance (x 
t
​
 ):
x 
t
​
 =(u 
t
(1)
​
 (b 
t
(1)
​
 −p 
t
​
 ),…,v 
t
(1)
​
 (a 
t
(1)
​
 −p 
t
​
 ),…)
(여기서 u,v는 각 호가의 물량, b,a는 가격을 의미함).
2.3 데이터 정규화 및 인코딩
Min-Max Normalization: 피처 간 가중치 불균형을 방지하기 위해 모든 연속형 변수를 동일 스케일로 조정합니다.
Categorical Encoding: Decision Tree 모델의 경우 종목명(Company) 및 산업군(Industry) 피처에 대해 Label Encoding을 적용하여 모델의 가독성과 연산 효율을 확보합니다.
3. 시스템 아키텍처 및 하이브리드 로직
3.1 기술적 분석 기반 매매 신호 (1차 필터)
Breakout Resistance Strategy: 이전 고점(Previous Maxima)으로 형성된 심리적 저항선을 가격이 상향 돌파하는 지점에서 1차 진입 신호를 생성합니다.
3.2 ML/DL 기반 거래 필터링 (2차 필터)
TA 전략이 도출한 거래 신호 중 실질적 수익 가능성이 높은 케이스를 선별합니다.
DNN (Deep Neural Network): **51개의 어트리뷰트(Attributes)**를 입력으로 하며, RMSProp 옵티마이저와 Binary Cross-Entropy 손실 함수를 사용합니다 (1 Hidden Layer, 9 Units).
XGBoost: 결정 트리 기반 앙상블 모델로, 다음 하이퍼파라미터를 준수합니다.
하이퍼파라미터
설정값
목적
max_depth
5
트리 복잡도 제어 및 과적합 방지
learning_rate
0.1
수렴 속도 및 학습 안정성 확보
n_estimators
500
부스팅 반복 횟수를 통한 성능 극대화
Decision Tree: 35개의 피처를 사용하며, Gini Impurity를 기준으로 이진 분류를 수행합니다 (Max Depth: 6).
3.3 강화학습(Q-Learning) 설계
시장 환경을 **Markov Decision Process (MDP) 튜플 (S,A,P,R,H,γ)**로 정의합니다.
상태(State, S): 오더북 요약 정보(x 
t
​
 )와 현재 인벤토리(s 
t
​
 )의 결합.
액션(Action, A): Discrete Action Space {−1(매도),0(홀드),+1(매수)}.
Q-함수 근사: 과적합 방지를 위해 tanh squashing function을 적용합니다.
Q(x 
t
​
 ,s 
t
​
 ,a)=tanh[(a+s 
t
​
 )⋅θ 
T
 x 
t
​
 ]−λ∣s 
t
​
 +a∣
(tanh는 비정상적 시장 움직임에 대한 과대 적합을 억제하며, λ 항은 과도한 포지션 보유를 규제함).
4. 진입 및 청산 전략 (Execution Logic)
4.1 진입 조건
저항선 돌파라는 기술적 신호와 ML 필터 모델이 계산한 '수익 확률(Probability of Profit)'이 사전에 정의된 임계값(Threshold)을 동시 충족할 때 집행합니다.
4.2 청산 및 리스크 관리
Stop Loss: 매수 가격 대비 일정 비율 하락 시 즉시 시장가 청산.
Trailing Stop: 수익 발생 시 가격 고점을 추적하며 청산 가격을 동적으로 상향 조정하여 이익을 보존합니다.
5. 보상 함수(Reward Function) 및 리스크 관리
5.1 수익 조정 보상 설계
단순 PnL이 아닌 위험 대비 수익 지표인 **샤프 지수(Sharpe Ratio)**와 하방 변동성만을 고려한 **소르티노 지수(Sortino Ratio)**를 보상에 반영합니다.
5.2 페널티 및 규제
최대 낙폭(MDD) 발생 시 강력한 음의 보상을 부여합니다.
규제항(Regularization term): 잦은 거래와 과도한 포지션 보유를 억제하기 위해 λ∣s 
t
​
 +a∣ 페널티를 부과합니다.
5.3 현실적 거래 비용 반영
대만 선물(Futures) 시장 사례를 참조하여 다음 비용을 보상 계산에 강제 적용합니다.
거래세(Tax): 계약 가치의 0.0004 적용.
증거금(Margin): 2007년 이후 적용된 단타매매 50% 증거금 할인 혜택 반영.
슬리피지(Slippage) 및 수수료: 실제 체결 오차를 포함하여 Net Return을 산출합니다.
6. 모델 검증 및 과적합 방지
6.1 검증 프로세스
Rolling Cross-Validation (전진 분석): 20002011년 학습 후 20112012년 테스트하는 방식을 순차 적용하여 시장 환경 변화(Regime Change)에 대한 견고성을 검증합니다.
6.2 구조적 최적화
XGBoost의 Regularization 기술을 적용하고, DNN의 은닉층 유닛 수를 엄격히 제한하여 훈련 데이터 매몰 현상을 방지합니다.
7. 백테스팅 및 성과 분석
7.1 Backtrader 기반 이벤트 드리븐 시뮬레이션
Cerebro 엔진 활용: 벡터 연산이 아닌 시계열 데이터를 순차적으로 처리하는 next() 메서드를 사용하여 주문 체결 지연 및 마찰 비용을 실제 시장과 유사하게 모사합니다.
7.2 성과 감사 (Audit)
PyFolio/QuantStats: 'Tear Sheet'를 생성하여 누적 수익률, 롤링 베타, 샤프 지수 등을 시각화합니다.
벤치마킹: S&P500 또는 관련 인덱스 대비 위험 조정 수익률의 우월성을 입증합니다.
8. 기술적 제약 및 실행 환경
Interactive Brokers (IB) API 연동: 실시간 데이터 수신 및 주문 집행을 위해 TWS/Gateway 설정을 최적화합니다.
비동기 이벤트 기반 처리: tickPrice 콜백(Callback) 함수를 활용한 Asynchronous 아키텍처를 구축하여 밀리초(ms) 단위의 데이터 수신 및 주문 집행 지연을 최소화해야 합니다.
확장성: 향후 시간 단위(Hourly)에서 주 단위(Weekly) 차트까지 대응 가능한 유연한 스케줄러 구조를 채택합니다.