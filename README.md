# BiciMAD refill detector
Recoge el estado de las estaciones BiciMAD (feed GBFS) y detecta a qué horas se reponen.

    python collector.py            # recolecta cada 60 s en bicimad.sqlite
    python detect_refills.py       # detecta eventos y genera gráficas en resultados/

Requisitos para el análisis: pandas, numpy, matplotlib
