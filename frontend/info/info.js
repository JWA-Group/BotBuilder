(function () {
  var links = Array.prototype.slice.call(document.querySelectorAll(".info-nav a[href^='#']"));
  if (!links.length) return;

  var sections = links
    .map(function (a) {
      var id = a.getAttribute("href").slice(1);
      return document.getElementById(id);
    })
    .filter(Boolean);

  function setActive(id) {
    links.forEach(function (a) {
      a.classList.toggle("is-active", a.getAttribute("href") === "#" + id);
    });
  }

  if ("IntersectionObserver" in window) {
    var visible = {};
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          visible[entry.target.id] = entry.isIntersecting;
        });
        var current = null;
        for (var i = 0; i < sections.length; i++) {
          if (visible[sections[i].id]) {
            current = sections[i].id;
            break;
          }
        }
        if (current) setActive(current);
      },
      { rootMargin: "-20% 0px -60% 0px", threshold: [0, 0.25, 0.5] }
    );
    sections.forEach(function (s) {
      observer.observe(s);
    });
  }

  if (location.hash) {
    setActive(location.hash.slice(1));
  } else if (sections[0]) {
    setActive(sections[0].id);
  }
})();
