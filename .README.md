# Simulator Results Publication

This is PoC quality. The following are some screencasts:

```bash
$ # install https://github.com/asciinema/asciinema/
$ asciinema play publish.cast
$ asciinema play view.cast
```

```bash
$ ./docker-build.sh
$ aws configure sso
```

```bash
$ cd tf
$ terraform init
$ terraform apply
```

```bash
$ # simulator from https://github.com/gbarnett-hz/hazelcast-simulator/tree/publish-results
$ # from within your simulator project directory
$ perftest create myproject
$ # the following coordinates are that of the table you created via terraform
$ HZ_SIM_PUBLISH=1 HZ_SIM_REGION=eu-west-1 HZ_SIM_TABLE=simulator_table perftest run tests.yaml
```

```bash
$ # if you want to view...
$ cd viewer
$ HZ_SIM_REGION=eu-west-1 HZ_SIM_TABLE=simulator_table ./sim-view 
```

For the viewer the versions and tests are defined for now in `config.json` which are copied into the docker image. 
