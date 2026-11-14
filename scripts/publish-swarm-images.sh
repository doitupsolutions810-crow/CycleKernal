#!/bin/sh
set -eu

REGISTRY=${CYCLEKERNEL_REGISTRY:-ghcr.io}
OWNER=${CYCLEKERNEL_REGISTRY_OWNER:-doitupsolutions810-crow}
TAG=${CYCLEKERNEL_IMAGE_TAG:-latest}
SERVICES='frontend simulation monitoring bridge terminal orchestrator chat colony'

for service in $SERVICES; do
  source_image="cyclekernel-${service}:latest"
  target_image="${REGISTRY}/${OWNER}/cyclekernel-${service}:${TAG}"
  docker image inspect "$source_image" >/dev/null
  docker tag "$source_image" "$target_image"
  docker push "$target_image"
done

printf 'Published all CycleKernel Swarm images to %s/%s with tag %s.\n' "$REGISTRY" "$OWNER" "$TAG"
