# plots.py (RL Sinyallerini Görselleştirebilen Nihai Hali)

import plotly.graph_objects as go
from plotly.subplots import make_subplots

def plot_chart(df, symbol, fib_levels, options, rl_signal_col=None):
    """
    Ana grafik fonksiyonu. Artık RL sinyallerini de (rl_signal_col)
    grafiğe ekleyebiliyor.
    """
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.08,
        row_heights=[0.45, 0.2, 0.2, 0.15],
        subplot_titles=(f'{symbol} Fiyat & Göstergeler', 'RSI & Stochastic', 'ADX & VWAP', 'Hacim')
    )

    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Fiyat'
    ), row=1, col=1)

    # ... (SMA, EMA, Bollinger, VWAP, Fibonacci çizimleri aynı kalacak) ...
    if options.get("show_sma"):
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA'], line=dict(color='purple'), name='SMA'), row=1, col=1)
    if options.get("show_ema"):
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA'], line=dict(color='green'), name='EMA'), row=1, col=1)
    if options.get("show_bbands"):
        fig.add_trace(go.Scatter(x=df.index, y=df['bb_hband'], line=dict(color='orange'), name='BB Üst'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['bb_lband'], line=dict(color='orange'), name='BB Alt',
                                 fill='tonexty', fillcolor='rgba(255,165,0,0.1)'), row=1, col=1)

    # Standart Al/Sat sinyallerini çiz
    buy_signals = df[df['Signal'] == 'Al']
    sell_signals = df[df['Signal'] == 'Short'] # 'Sat' yerine 'Short' kullanılıyor olabilir
    fig.add_trace(go.Scatter(
        x=buy_signals.index, y=buy_signals['Low']*0.995,
        mode='markers', marker=dict(color='green', size=12, symbol='arrow-up'),
        name='Al'
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=sell_signals.index, y=sell_signals['High']*1.005,
        mode='markers', marker=dict(color='red', size=12, symbol='arrow-down'),
        name='Sat/Short'
    ), row=1, col=1)

    # --- YENİ: RL Ajanı Sinyallerini Çiz ---
    if rl_signal_col and rl_signal_col in df.columns:
        rl_buys = df[df[rl_signal_col] == 'Al']
        rl_sells = df[df[rl_signal_col] == 'Sat']
        fig.add_trace(go.Scatter(
            x=rl_buys.index, y=rl_buys['Low']*0.985,
            mode='markers', marker=dict(color='cyan', size=10, symbol='triangle-up'),
            name='RL AL'
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=rl_sells.index, y=rl_sells['High']*1.015,
            mode='markers', marker=dict(color='fuchsia', size=10, symbol='triangle-down'),
            name='RL SAT'
        ), row=1, col=1)

    # ... (RSI, ADX, Hacim gibi alt grafikler aynı kalacak) ...
    fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='blue'), name='RSI'), row=2, col=1)
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='Hacim', marker_color='lightblue'), row=4, col=1)


    fig.update_layout(
        height=850,
        showlegend=True,
        xaxis_rangeslider_visible=False
    )
    return fig


def plot_performance_summary(equity_curve, drawdown_series):
    """
    Sermaye eğrisini ve düşüş dönemlerini gösteren bir özet grafiği oluşturur.
    """
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
        subplot_titles=('Sermaye Eğrisi (Equity Curve)', 'Düşüş Grafiği (Drawdown)')
    )

    # Sermaye Eğrisi
    fig.add_trace(go.Scatter(
        x=equity_curve.index, y=equity_curve['equity'],
        mode='lines', name='Sermaye',
        line=dict(color='blue', width=2)
    ), row=1, col=1)

    # Düşüş Grafiği
    fig.add_trace(go.Scatter(
        x=drawdown_series.index, y=drawdown_series * 100,  # Yüzde olarak göstermek için 100 ile çarp
        mode='lines', name='Düşüş',
        fill='tozeroy', line=dict(color='red', width=1)
    ), row=2, col=1)

    fig.update_layout(
        height=600,
        showlegend=False,
        yaxis1_title="Sermaye",
        yaxis2_title="Düşüş (%)",
        yaxis1_tickprefix="$",
        yaxis2_ticksuffix="%"
    )

    return fig