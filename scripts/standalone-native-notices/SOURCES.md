# Native components of the standalone DBLift package

This directory adds notices for the identified native components of the
Psycopg Binary and pymssql wheels listed in `audited-wheels.txt`. See the parent
directory for Python package notices and hashes of the bundled native files.

## Sources by target

| Wheel and target | Native components | Build evidence |
| --- | --- | --- |
| Psycopg Binary 3.3.9, Linux x86-64 and macOS arm64 | libpq 18.6, OpenSSL 3.5.9, MIT Kerberos 1.22.2 and OpenLDAP 2.6.16 | [Matched wheel build](https://github.com/psycopg/psycopg/actions/runs/43127304274) and [native build recipe](https://github.com/psycopg/psycopg/blob/bced8a8993064a378d5ca852215d99f73f4c6cae/tools/ci/build_libpq.sh) |
| Psycopg Binary 3.3.9, Linux x86-64 | libcom_err from e2fsprogs 1.42.9-19.el7, keyutils 1.5.8-3.el7, Cyrus SASL 2.1.26-24.el7_9 and libxcrypt 4.5.2 | The ELF build IDs for libcom_err, keyutils and Cyrus SASL match the manylinux build image RPM files. The libxcrypt file matches the auditwheel hash prefix and the image's pkg-config version. |
| Psycopg Binary 3.3.9, Windows x64 | libpq 18.4, OpenSSL 3.6.5, LZ4 1.10.0 and zlib 1.3.2 | [Matched Windows wheel build](https://github.com/psycopg/psycopg/actions/runs/43127304274) and its vcpkg configuration |
| pymssql 2.4.6, Linux x86-64 | Statically linked FreeTDS 1.5.19, OpenSSL from AlmaLinux RPM `openssl-libs-1.1.1k-18.el8_6.x86_64` | [Matched Linux wheel build](https://github.com/pymssql/pymssql/actions/runs/40436287488/job/121965692619) and [AlmaLinux advisory](https://errata.almalinux.org/8/ALSA-2026-85968.html). The ELF build IDs and auditwheel hash prefixes for libssl and libcrypto match the RPM. |
| pymssql 2.4.5, macOS arm64 | Statically linked FreeTDS 1.5.19, OpenSSL 3.6.3 | [Matched macOS wheel build](https://github.com/pymssql/pymssql/actions/runs/39343251230/job/118369636627) and the version string in the bundled libcrypto |
| pymssql 2.4.6, Windows x64 | Statically linked FreeTDS 1.5.19, OpenSSL 4.0.3 in the compiled extension | [Matched Windows wheel build](https://github.com/pymssql/pymssql/actions/runs/40436287488/job/121965614293) and the version strings in the compiled extension |

Upstream source references:

- PostgreSQL [18.6](https://github.com/postgres/postgres/tree/REL_18_6) and
  [18.4](https://github.com/postgres/postgres/tree/REL_18_4).
- OpenSSL [3.5.9](https://github.com/openssl/openssl/tree/openssl-3.5.9),
  [3.6.3](https://github.com/openssl/openssl/tree/openssl-3.6.3),
  [3.6.5](https://github.com/openssl/openssl/tree/openssl-3.6.5) and
  [4.0.3](https://github.com/openssl/openssl/tree/openssl-4.0.3).
  The license file is byte-identical across these tags. The Linux pymssql wheel
  uses [the AlmaLinux packaging tree and patches](https://git.almalinux.org/rpms/openssl/src/tag/imports/c8/openssl-1.1.1k-18.el8_6).
  The notice comes from the exact binary RPM. The corresponding
  [AlmaLinux source RPM](https://vault.almalinux.org/8.10/BaseOS/Source/Packages/openssl-1.1.1k-18.el8_6.src.rpm)
  has SHA-256 `c1bfee60358147ce916a310817311674abb29f8956f9a09d7e3a30a2aec850f8`.
- MIT Kerberos [1.22.2](https://github.com/krb5/krb5/tree/krb5-1.22.2-final),
  OpenLDAP [2.6.16](https://git.openldap.org/openldap/openldap/-/tree/OPENLDAP_REL_ENG_2_6_16)
  and libxcrypt [4.5.2](https://github.com/besser82/libxcrypt/tree/v4.5.2).
- LZ4 [1.10.0](https://github.com/lz4/lz4/tree/v1.10.0) and
  zlib [1.3.2](https://github.com/madler/zlib/tree/v1.3.2).
- FreeTDS [1.5.19 source archive](https://www.freetds.org/files/stable/freetds-1.5.19.tar.gz)
  SHA-256 `ff70d0c8ae8dd23e7b1314274d6e9d30b479998415760b3fa656754b737c2bd6`.
  See the pymssql build recipes for
  [2.4.5](https://github.com/pymssql/pymssql/blob/23d33502dfd3f291345e2bf9155c31a40d33b481/dev/build.py)
  and [2.4.6](https://github.com/pymssql/pymssql/blob/8c23b48486077146b01abbe91614cf640202f1b9/dev/build.py).

| CentOS Linux 7 source RPM | SHA-256 |
| --- | --- |
| [e2fsprogs-1.42.9-19.el7.src.rpm](https://vault.centos.org/7.9.2009/os/Source/SPackages/e2fsprogs-1.42.9-19.el7.src.rpm) | `718f64bd465d1770eaf6490157a861d3dba2846b4a636a67d27bd4d38e6b86cf` |
| [keyutils-1.5.8-3.el7.src.rpm](https://vault.centos.org/7.9.2009/os/Source/SPackages/keyutils-1.5.8-3.el7.src.rpm) | `eff16e16f707fd28436afe4cf7b7c2e34b9f827e7f6beacf3c6eecbf74e9f850` |
| [cyrus-sasl-2.1.26-24.el7_9.src.rpm](https://vault.centos.org/7.9.2009/updates/Source/SPackages/cyrus-sasl-2.1.26-24.el7_9.src.rpm) | `c49472bd08c6060f53a9dace005b81cf466836790d2dcb407a536820f6319e77` |

These references record provenance for the identified components. Before public
redistribution, complete the audit of the other bundled native components and
provide the corresponding sources and relinking materials where applicable,
including for the statically linked FreeTDS extensions.
