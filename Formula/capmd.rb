class Capmd < Formula
  desc "Recorta el capítulo de un libro y lo deja en Markdown limpio, listo para estudiar"
  homepage "https://github.com/martin-araya/capmd"
  url "https://github.com/martin-araya/capmd/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "84a08459252e09f464db41b200e265bcb0e25db77afbd6d6df4f9ff4a556aee3"
  license "MIT"

  depends_on "python@3.12"

  # Recursos del virtualenv: las deps de capmd que NO están en Homebrew
  # se instalan via pip dentro de venv_install_with_resources.  Las URLs
  # y sha256 están pinneadas a versiones específicas para que el install
  # sea offline-determinista y reproducible.
  resource "typer" do
    url "https://files.pythonhosted.org/packages/c5/58/a79003b91ac2c6890fc5d90145c662fd5771c6f11447f116b63300436bc9/typer-0.12.5.tar.gz"
    sha256 "f592f089bedcc8ec1b974125d64851029c3b1af145f04aca64d69410f0c9b722"
  end

  resource "markitdown" do
    url "https://files.pythonhosted.org/packages/59/93/e8a4af0c47551beb6383e226e840cbc811a577b8096eb385251b3fcc8f62/markitdown-0.1.7.tar.gz"
    sha256 "4d1f3c69cd43b82288fdc3653686d759dcf355ee7c681aa6a855aed98a1e4f44"
  end

  resource "pypdf" do
    url "https://files.pythonhosted.org/packages/b1/f2/e2e8b886ee248c2d7e8c054009882636b1120599ea35159c184947f9d1d3/pypdf-5.0.0.tar.gz"
    sha256 "5c536ec0f7af8e2f80eb32806964652a562b9abc5477b3c195e2b842725ce55b"
  end

  resource "pypdfium2" do
    url "https://files.pythonhosted.org/packages/a1/14/838b3ba247a0ba92e4df5d23f2bea9478edcfd72b78a39d6ca36ccd84ad2/pypdfium2-4.30.0.tar.gz"
    sha256 "48b5b7e5566665bc1015b9d69c1ebabe21f6aee468b509531c3c8318eeee2e16"
  end

  resource "PyYAML" do
    url "https://files.pythonhosted.org/packages/54/ed/79a089b6be93607fa5cdaedf301d7dfb23af5f25c398d5ead2525b063e17/pyyaml-6.0.2.tar.gz"
    sha256 "d584d9ec91ad65861cc08d42e834324ef890a082e591037abe114850ff7bbc3e"
  end

  resource "Pillow" do
    url "https://files.pythonhosted.org/packages/cd/74/ad3d526f3bf7b6d3f408b73fde271ec69dfac8b81341a318ce825f2b3812/pillow-10.4.0.tar.gz"
    sha256 "166c1cd4d24309b30d61f79f4a9114b7b2313d7450912277855ff5dfd7cd4a06"
  end

  resource "EbookLib" do
    url "https://files.pythonhosted.org/packages/e8/1d/90bb33317d756c25b40bb55312dda30a94afb691755763fc00976250c82b/EbookLib-0.18.tar.gz"
    sha256 "38562643a7bc94d9bf56e9930b4927e4e93b5d1d0917f697a6454db5a1c1a533"
  end

  resource "symspellpy" do
    url "https://files.pythonhosted.org/packages/34/12/5adaecab0ab0122a70ec1cca5ff177bff1f5fc2c352b067026ad357a64ee/symspellpy-6.7.0.tar.gz"
    sha256 "d06d50db8bf0907998689b2fd2fb1c26c660cde7a4d2ffb67efc5ae5e3763905"
  end

  resource "rich" do
    url "https://files.pythonhosted.org/packages/b3/01/c954e134dc440ab5f96952fe52b4fdc64225530320a910473c1fe270d9aa/rich-13.7.1.tar.gz"
    sha256 "9be308cb1fe2f1f57d67ce99e95af38a1e2bc71ad9813b0e247cf7ffbcc3a432"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "capmd", shell_output("#{bin}/capmd --version")
    assert_match "convert", shell_output("#{bin}/capmd --help")
  end

  bottle do
    # Bottle file sha256 will be filled by `brew bottle` (see scripts/build-bottles.sh).
    # Estas líneas son REEMPLAZADAS por brew bottle al generar la botella; las
    # entradas reales se commitean después de cada release con `release.sh`.
    #
    # Para regenerar (en el OS target, no en cross-compile):
    #   brew tap martin-araya/capmd <repo>
    #   brew install --build-bottle ./Formula/capmd.rb
    #   brew bottle --root-url "https://github.com/martin-araya/capmd/releases/download/vX.Y.Z" ./Formula/capmd.rb
    #
    # Para el MVP de I4 shippeamos bottles solo del OS del maintainer (ver
    # README.md sección "Homebrew"); la otra variante se agrega via cross-build
    # o VM con `brew test-bot` cuando se requiera.
  end
end
