# Roteiro rápido de coleta em bancada

Classes: **parado, normal, desbalanceado_leve, desbalanceado_forte, desalinhado** (calço sob o motor).
Meta: **4 sessões** (cada uma com o sensor remontado), **1 velocidade (1000 RPM)**, gravações de **30 s**.
São 20 gravações (10 min gravando), cerca de **45 min** no total.

## As falhas

| Classe | Como provocar |
|---|---|
| `parado` | motor desligado, sem nada preso |
| `normal` | sem peso, sem calço |
| `desbalanceado_leve` | peso **pequeno** preso ao eixo |
| `desbalanceado_forte` | peso **grande** preso ao eixo, **no mesmo ponto** de fixação do leve |
| `desalinhado` | calço sob **um** pé do motor, peso retirado |

**Sobre o calço:** o motor fica **solto sobre a bancada, apoiado só no próprio peso**, sem parafusos. Calçar **um** pé
deixa o motor inclinado, apoiado de forma irregular (pé manco, *soft foot*), e o eixo sai de alinhamento com a bancada.
A assinatura esperada é **1× e 2× da rotação**, com mais energia no eixo axial.

- Calço de **0,5 a 1 mm** (lâmina de latão ou camadas de papel-cartão) sob **um** pé; os outros três ficam apoiados.
- Use sempre o **mesmo calço no mesmo pé** em todas as sessões e anote a espessura.
- Se ficar igual ao `normal` no espectro, aumente a espessura aos poucos.
- Motor solto pode "andar" na bancada com a vibração. **Marque o contorno do motor** e recoloque-o na marca em toda
  gravação. Fique de olho nele e desligue se começar a deslocar.

## Antes de começar

1. Fixe o sensor **rígido** na carcaça (parafuso, resina ou cola; fita dupla-face macia estraga o sinal), longe do peso.
   Mantenha a orientação: **X radial horizontal, Y axial, Z radial vertical**. Fotografe a montagem.
2. Velocidade única: **1000 RPM**. Ajuste o motor para 1000 RPM e confira (inversor ou tacômetro). No campo *Velocidade*
   da página, escreva `1000rpm` em todas as gravações com o motor ligado.
3. Separe o peso pequeno, o peso grande e o calço. Anote as massas e a espessura.
4. Configuração de cada gravação: **duração 30 s**, **atraso 5 s**, **descartar 2 s**. Em *Notas*, escreva o que estiver montado (massa, espessura do calço).

## Por sessão (repita 4 vezes)

**Nova sessão = remontar o sensor** (soltar e fixar de novo) e somar 1 no campo *Sessão*. Sem remontar, a validação do
modelo fica otimista.

Em cada gravação: ajuste o motor, espere **~15 s** para a rotação estabilizar, preencha classe e velocidade, comece a
gravar, **afaste-se** (a mão perto do motor também vibra) e espere os 30 s.

**Troque a falha sempre com o motor desligado.**

| Ordem | Classe |
|---|---|
| 1 | `parado` |
| 2 | `normal` |
| 3 | `desbalanceado_leve` |
| 4 | `desbalanceado_forte` |
| 5 | `desalinhado` |

São 5 gravações por sessão, 20 no total. **Embaralhe a ordem das classes de uma sessão para outra** (por exemplo,
sessão 1 como na tabela, sessão 2 de trás para frente). Assim a classe não fica amarrada à temperatura do motor.

## Depois de cada gravação

- Confira o selo de qualidade: tem que estar **ok**, sem pacotes perdidos. Se não estiver, regrave.
- Guarde os arquivos `.npy` e `.json` de cada gravação, sem renomear.
