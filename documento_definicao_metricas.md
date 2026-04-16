**O QUE VAMOS TRATAR E COMO VAMOS TRATAR:**



**CPU:**

&nbsp;	Pegar frequencia mínima frequencia atual e frequencia máxima para comparar com o percentual de uso:

        	Quando a frequencia atual está baixa porém o percentual de uso está alto, isso indica degradação da CPU.

            	Quando a frequencia atual está abaixo da mínima isso indica que o sistema está em modo economia de energia ou que a CPU está muito quente o que 

            	força a máquina diminuir a frequencia.

&nbsp;	**O problema acima se chama THERMAL THROTTLING que é um mecanismo que reduz automaticamente a velocidade (clock) e a tensão do processador quando este atinge temperaturas perigosas, causando perda de desempenho.**

&nbsp;	Pegar o percentual de uso e comparar com limite no mysql 

        	percentual\_cpu\_atual >= limite = Status Crítico

            	percentual\_cpu\_atual >= limite - 15 = Status Atenção

            	percentual\_cpu\_atual < limite - 15 = Status normal

&nbsp;	**Essa métrica responde se a CPU está sobrecarregada ou não com base no status e no limite**

&nbsp;	MÉTRICAS:

        	psutil.cpu\_percent()

            	psutil.cpu\_freq().current

            	psutil.cpu\_freq().max

            	psutil.cpu\_freq().min

**RAM:** 

&nbsp;	**SWAP**

&nbsp;	Pegar dados de memória swap que é uma forma que o SO usa de quando a RAM está sobrecarregada, usar o disco/ssd como memória temporária:

&nbsp;		O psutil.swap\_memory() traz dados como:

&nbsp;			total -> Total que o sistema pode utilizar do disco como RAM

&nbsp;			usado -> O quanto está sendo utilizado

&nbsp;			sin → dados entrando do swap (disco → RAM)

&nbsp;			sout → dados saindo da RAM pro swap

&nbsp;		Qual é o problema? **Utilizar o disco como swap é porque a RAM não está aguentando, com isso, quando o percentual de uso de swap está muito grande:**

			percentual\_uso\_swap = (used / total) \* 100



&nbsp;			percentual\_uso\_swap > 0% – 5%     → NORMAL

&nbsp;			percentual\_uso\_swap > 5% – 20%    → ATENÇÃO

&nbsp;			percentual\_uso\_swap > 20% – 50%   → ALERTA

&nbsp;			percentual\_uso\_swap > 50%       → CRÍTICO



&nbsp;	**Percentual de uso (%)** - virtual\_memory

&nbsp;	Pegar o percentual de uso e comparar com limite no mysql 

        	percentual\_ram\_atual >= limite = Status Crítico

            	percentual\_ram\_atual >= limite - 15 = Status Atenção

&nbsp;		percentual\_ram\_atual < limite - 15 = Status normal

 	**Essa métrica responde se a RAM está sobrecarregada ou não com base no status e no limite**

      	

      MÉTRICAS:

&nbsp;		psutil.virtual\_memory()

&nbsp;		psutil.swap\_memory()

            

**DISCO:**

	**Percentual de uso total (%)**

	Pegar os dados de percentual de uso do disco para o cliente saber se está próximo do limite, se passou para não estourar o disco:

&nbsp;		percentual\_uso\_disco >= limite = Status Crítico

            	percentual\_uso\_disco >= limite - 15 = Status Atenção

            	percentual\_uso\_disco < limite - 15 = Status normal



&nbsp;	**Tempo gasto de leitura e escrita por processo - Indica gargalo**

	Pegar os dados de disk\_counters como o Número de leituras realizadas, Número de escritas realizadas, Número de bytes lidos, Número de bytes escritos, Tempo gasto lendo do disco (em milissegundos),

&nbsp;	Tempo gasto escrevendo no disco (em milissegundos).

&nbsp;	Pega um intervalo e verifica



**PROCESSOS:**

	Pegar todas as métricas de processos no psutil porém, filtrando os processos que estão consumindo mais do que 5% de MEMÓRIA RAM,

&nbsp;	Para depois tratar, esses processos responderão o que está causando os problemas de hardware.



**LATÊNCIA:**

	Pegar a velocidade de tempo de conexão com o outro dispositivo, caso o tempo de conexão seja muito alto significa que a comunicação está sendo afetada











