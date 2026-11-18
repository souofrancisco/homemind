# Utilitários de visão usados pela presença

`features/presence/yolo.py` importa `dispositivo.py` para escolher CPU/CUDA/MPS e usa os pesos
YOLO de pessoas preparados por `pesos.py`. O processamento fica local; o modelo da presença
recebe apenas o recorte configurado da soleira e não usa pose nem reconhecimento facial.

`pesos.py` descarrega `yolo11{s,n}.pt` para `VISAO_PASTA_MODELOS`; não é chamado no arranque nem
nos testes. `dispositivo.py` não importa PyTorch até ser pedida a seleção automática.
