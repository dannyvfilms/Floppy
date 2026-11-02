"""Check that a published image index carries SBOM and provenance whose subjects
are its own platform digests. Usage: verify_image_attestations.py REPO DIGEST
(REPO like ghcr.io/owner/name). Optional GHCR_USER/GHCR_TOKEN for private reads.
Any missing or mismatched object raises, so a failure can never look clean."""

import base64
import json
import os
import sys
import urllib.request

MANIFEST = ",".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
    ]
)


def main(repo, digest):
    host, name = repo.split("/", 1)
    req = urllib.request.Request(
        f"https://{host}/token?scope=repository:{name}:pull"
    )
    if os.environ.get("GHCR_TOKEN"):
        cred = f"{os.environ.get('GHCR_USER', 'x')}:{os.environ['GHCR_TOKEN']}"
        req.add_header("Authorization", "Basic " + base64.b64encode(cred.encode()).decode())
    token = json.load(urllib.request.urlopen(req))["token"]

    def get(kind, ref):
        r = urllib.request.Request(
            f"https://{host}/v2/{name}/{kind}/{ref}",
            headers={"Authorization": f"Bearer {token}", "Accept": MANIFEST},
        )
        return json.load(urllib.request.urlopen(r))

    manifests = get("manifests", digest)["manifests"]
    images = {
        m["digest"]: m["platform"]
        for m in manifests
        if m.get("platform", {}).get("os") == "linux"
    }
    assert {p["architecture"] for p in images.values()} >= {"amd64", "arm64"}, images
    attest = {
        m["digest"]: m["annotations"]["vnd.docker.reference.digest"]
        for m in manifests
        if m.get("annotations", {}).get("vnd.docker.reference.type")
        == "attestation-manifest"
    }
    assert set(attest.values()) == set(images), (attest, images)
    for att_digest, subject in attest.items():
        kinds = set()
        for layer in get("manifests", att_digest)["layers"]:
            kind = layer["annotations"]["in-toto.io/predicate-type"]
            statement = get("blobs", layer["digest"])
            subjects = {f"sha256:{s['digest']['sha256']}" for s in statement["subject"]}
            assert subject in subjects, (kind, subject, subjects)
            assert statement.get("predicate"), (kind, "empty predicate")
            kinds.add(kind)
        assert "https://spdx.dev/Document" in kinds, kinds
        assert "https://slsa.dev/provenance/v1" in kinds, kinds
    print(f"{repo}@{digest}: SBOM + provenance bind {sorted(images)}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
