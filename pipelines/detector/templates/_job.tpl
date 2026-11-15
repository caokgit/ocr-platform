{{/* What both steps share: the image, the environment, the code mounts (docs/specs/training-platform.md#the-job). */}}
{{- define "detector.env" -}}
- {name: MLFLOW_TRACKING_URI, value: {{ .Values.mlflowUri | quote }}}
- {name: MLFLOW_KEEP_RUN_ACTIVE, value: "true"}
- {name: S3_ENDPOINT, value: {{ .Values.s3Endpoint | quote }}}
- name: AWS_ACCESS_KEY_ID
  valueFrom: {secretKeyRef: {name: {{ .Values.s3Secret }}, key: AWS_ACCESS_KEY_ID}}
- name: AWS_SECRET_ACCESS_KEY
  valueFrom: {secretKeyRef: {name: {{ .Values.s3Secret }}, key: AWS_SECRET_ACCESS_KEY}}
- {name: LAB_GIT_COMMIT, value: {{ .Values.gitCommit | quote }}}
- {name: IMAGE_REF, value: {{ .Values.image | quote }}}
- {name: ARGO_WORKFLOW, value: "{{`{{workflow.name}}`}}"}
- {name: WORK, value: /work}
- {name: HOME, value: /work}
- {name: YOLO_CONFIG_DIR, value: /work/cfg}
- {name: MPLCONFIGDIR, value: /work/mpl}
- {name: PYTHONPATH, value: /work/deps:/code}
- {name: PYTHONUNBUFFERED, value: "1"}
{{- end -}}
{{- define "detector.mounts" -}}
- {name: work, mountPath: /work}
- {name: shm, mountPath: /dev/shm}
- {name: code, mountPath: /code}
- {name: recipes, mountPath: /code/recipes}
{{- end -}}
{{- define "detector.volumes" -}}
- {name: work, emptyDir: {sizeLimit: 8Gi}}
- {name: shm, emptyDir: {medium: Memory, sizeLimit: 1Gi}}
- {name: code, configMap: {name: detector-code}}
- {name: recipes, configMap: {name: detector-recipes}}
{{- end -}}
{{- define "detector.run" -}}
- bash
- -c
- |
  set -euo pipefail
  python -m pip install --quiet --disable-pip-version-check --no-deps --require-hashes --target /work/deps -r /code/requirements.txt
  exec python /code/{{ . }}
{{- end -}}
