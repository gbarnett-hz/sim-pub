```bash
$ ./build.sh
$ aws configure sso # hack for local run
$ aws cloudformation deploy --template-file cloudformation.yaml --stack-name $NAME
$ ./sim-view
```
