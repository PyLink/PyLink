local test(py_version) = {
  "kind": "pipeline",
  "type": "docker",
  "name": "test-" + py_version,
  "steps": [
    {
      "name": "test",
      "image": "python:" + py_version,
      "commands": [
        "git submodule update --recursive --remote --init",
        "pip install -r requirements-docker.txt",
        "python3 setup.py install",
        "python3 -m unittest discover test/ --verbose"
      ]
    }
  ]
};

local build_docker(py_version) = {
  "kind": "pipeline",
  "type": "docker",
  "name": "build_docker",
  "steps": [
    {
      "name": "set Docker image tags",
      "image": "bash",
      "commands": [
        "bash .drone-write-tags.sh $DRONE_TAG > .tags",
        "# Will build the following tags:",
        "cat .tags"
      ]
    },
    {
      "name": "build Docker image",
      "image": "plugins/docker",
      "settings": {
        "repo": "jlu5/pylink",
        "username": {
          "from_secret": "docker_user"
        },
        "password": {
          "from_secret": "docker_token"
        }
      }
    }
  ],
  "trigger": {
    "event": [
      "push"
    ],
    "branch": ["release"],
  },
  "depends_on": ["test-" + py_version]
};

local deploy_pypi(py_version) = {
  "kind": "pipeline",
  "type": "docker",
  "name": "deploy_pypi",
  "steps": [
    {
      "name": "pypi_publish",
      "image": "plugins/pypi",
      "settings": {
        "username": "__token__",
        "password": {
            "from_secret": "pypi_token"
        }
      }
    }
  ],
  "trigger": {
    "event": [
      "tag"
    ],
    "ref": {
      "exclude": [
        "refs/tags/*alpha*",
        "refs/tags/*beta*",
        "refs/tags/*dev*"
      ]
    }
  },
  "depends_on": ["test-" + py_version]
};

[
    test("3.7"),
    test("3.8"),
    test("3.9"),
    test("3.10"),
    deploy_pypi("3.10"),
    build_docker("3.10"),
]
