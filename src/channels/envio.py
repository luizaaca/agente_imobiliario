"""Quais canais recebem mensagem por iniciativa nossa."""

# Canais em que o sistema consegue mandar mensagem sem a pessoa ter acabado de
# escrever — o follow-up precisa disso. No Streamlit a conversa só existe
# enquanto a pessoa está com a tela aberta: a mensagem fica gravada e aparece
# no chat dela, e isso é o desfecho normal, não uma falha de envio.
#
# Um conjunto só, consultado pelo remetente, pelo ciclo de follow-up e pelo
# despacho do que ficou pendente — se cada um tivesse o seu, um canal novo
# entraria em um e não nos outros.
CANAIS_COM_ENVIO = frozenset({"telegram"})
