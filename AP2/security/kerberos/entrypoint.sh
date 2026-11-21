#!/bin/bash
# KDC do realm ENADE.LOCAL.
# Na 1a execucao cria o banco, os principals dos servicos e os keytabs (volume /keytabs).
# O arquivo /keytabs/.pronto sinaliza aos demais servicos que os keytabs existem.
set -e
REALM=${KRB_REALM:-ENADE.LOCAL}
mkdir -p /var/lib/krb5kdc /keytabs

cat > /var/lib/krb5kdc/kdc.conf <<EOF
[kdcdefaults]
  kdc_ports = 88

[realms]
  $REALM = {
    database_name = /var/lib/krb5kdc/principal
    key_stash_file = /var/lib/krb5kdc/.k5.$REALM
    acl_file = /var/lib/krb5kdc/kadm5.acl
    max_life = 10h 0m 0s
    max_renewable_life = 7d 0h 0m 0s
  }
EOF
echo "*/admin@$REALM *" > /var/lib/krb5kdc/kadm5.acl
export KRB5_KDC_PROFILE=/var/lib/krb5kdc/kdc.conf

if [ ! -f /var/lib/krb5kdc/principal ]; then
  kdb5_util create -s -r "$REALM" -P "$KRB_MASTER_PASSWORD"
fi

# arquivo-keytab -> principal. Um principal por papel (privilegio minimo).
declare -A SERVICOS=(
  [kafka]="kafka/kafka"             # broker Kafka
  [kafka-admin]="kafka-admin"       # operacoes administrativas (topicos, health check)
  [produtor]="produtor"             # publica em enade.questoes
  [consumidor]="consumidor"         # le do Kafka e indexa no Elasticsearch
  [api]="api"                       # le do Elasticsearch
  [elasticsearch]="HTTP/elasticsearch"  # servico HTTP do Elasticsearch (SPNEGO)
)
for arq in "${!SERVICOS[@]}"; do
  princ="${SERVICOS[$arq]}@$REALM"
  # getprinc retorna 0 mesmo quando o principal nao existe: testar a saida
  kadmin.local -q "getprinc $princ" 2>&1 | grep -q "^Principal: $princ" \
    || kadmin.local -q "addprinc -randkey $princ"
  if [ ! -f "/keytabs/$arq.keytab" ]; then
    kadmin.local -q "ktadd -k /keytabs/$arq.keytab $princ"
  fi
done
chmod 0644 /keytabs/*.keytab   # laboratorio: leitura pelos usuarios dos containers
touch /keytabs/.pronto
echo "KDC pronto: $(ls /keytabs | tr '\n' ' ')"

exec krb5kdc -n
