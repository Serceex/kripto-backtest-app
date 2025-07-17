import plotly.graph_objects as go
from plotly.subplots import make_subplots

def plot_chart(df, symbol, fib_levels, options, ml_signal=False):
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.08,
        row_heights=[0.45, 0.2, 0.2, 0.15],
        subplot_titles=(f'{symbol} Fiyat & Göstergeler', 'RSI & Stochastic', 'ADX & VWAP', 'Hacim')
    )

    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Fiyat'
    ), row=1, col=1)

    if options.get("show_sma"):
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA'], line=dict(color='purple'), name='SMA'), row=1, col=1)
    if options.get("show_ema"):
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA'], line=dict(color='green'), name='EMA'), row=1, col=1)
    if options.get("show_bbands"):
        fig.add_trace(go.Scatter(x=df.index, y=df['bb_hband'], line=dict(color='orange'), name='BB Üst'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['bb_lband'], line=dict(color='orange'), name='BB Alt',
                                 fill='tonexty', fillcolor='rgba(255,165,0,0.1)'), row=1, col=1)
    if options.get("show_vwap"):
        fig.add_trace(go.Scatter(x=df.index, y=df['VWAP'], line=dict(color='cyan', dash='dot'), name='VWAP'), row=1, col=1)

    if options.get("show_fibonacci"):
        for lvl_name, lvl_price in fib_levels.items():
            fig.add_hline(y=lvl_price, line_dash="dash", annotation_text=lvl_name,
                          annotation_position="right", line_color="gray", row=1, col=1)

    # Statik sinyaller
    buy_signals = df[df['Buy_Signal']]
    sell_signals = df[df['Sell_Signal']]
    fig.add_trace(go.Scatter(
        x=buy_signals.index, y=buy_signals['Low']*0.995,
        mode='markers', marker=dict(color='green', size=12, symbol='arrow-up'),
        name='Al'
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=sell_signals.index, y=sell_signals['High']*1.005,
        mode='markers', marker=dict(color='red', size=12, symbol='arrow-down'),
        name='Sat'
    ), row=1, col=1)

    # ML sinyaller
    if ml_signal and 'ML_Signal' in df.columns:
        ml_buys = df[df['ML_Signal'] == 1]
        ml_sells = df[df['ML_Signal'] == -1]
        fig.add_trace(go.Scatter(
            x=ml_buys.index, y=ml_buys['Low']*0.98,
            mode='markers', marker=dict(color='lime', size=10, symbol='triangle-up'),
            name='ML AL'
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=ml_sells.index, y=ml_sells['High']*1.02,
            mode='markers', marker=dict(color='red', size=10, symbol='triangle-down'),
            name='ML SAT'
        ), row=1, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='blue'), name='RSI'), row=2, col=1)
    fig.update_yaxes(range=[0, 100], row=2, col=1)
    if options.get("show_stoch"):
        fig.add_trace(go.Scatter(x=df.index, y=df['Stoch_k'], line=dict(color='magenta', dash='dot'), name='Stoch %K'), row=2, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Stoch_d'], line=dict(color='magenta'), name='Stoch %D'), row=2, col=1)

    if options.get("show_adx"):
        fig.add_trace(go.Scatter(x=df.index, y=df['ADX'], line=dict(color='brown'), name='ADX'), row=3, col=1)
    if options.get("show_vwap"):
        fig.add_trace(go.Scatter(x=df.index, y=df['VWAP'], line=dict(color='cyan', dash='dot'), name='VWAP (Alt)'), row=3, col=1)

    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='Hacim', marker_color='lightblue'), row=4, col=1)

    fig.update_layout(height=1000, showlegend=True, xaxis_rangeslider_visible=False)
    return fig
