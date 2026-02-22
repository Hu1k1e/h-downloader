import traceback
try:
    import backend.main
except Exception as e:
    with open('error-trace.txt', 'w', encoding='utf-8') as f:
        traceback.print_exc(file=f)
