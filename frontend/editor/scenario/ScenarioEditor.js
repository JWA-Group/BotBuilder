/**
 * ScenarioEditor — thin facade over canvas connection rendering + editor hooks.
 */
(function (global) {
  "use strict";

  function getCanvas() {
    return global.ScenarioCanvas || global.Canvas || null;
  }

  function wireFromMain(ctx) {
    var C = getCanvas();
    if (!C || !C.bind) return null;
    return C.bind({
      getWrapper: function () {
        return ctx.canvasWrapper || document.getElementById("canvas-wrapper");
      },
      getSvg: function () {
        return (
          ctx.svg ||
          document.getElementById("connections-layer") ||
          document.querySelector("svg.connections")
        );
      },
      getPanX: function () {
        return typeof ctx.getPanX === "function" ? ctx.getPanX() : ctx.panX || 0;
      },
      getPanY: function () {
        return typeof ctx.getPanY === "function" ? ctx.getPanY() : ctx.panY || 0;
      },
      getScale: function () {
        return typeof ctx.getScale === "function" ? ctx.getScale() : ctx.scale || 1;
      },
      getBlocks: function () {
        return typeof ctx.getBlocks === "function" ? ctx.getBlocks() : ctx.blocks || [];
      },
      getConnections: function () {
        return typeof ctx.getConnections === "function"
          ? ctx.getConnections()
          : ctx.connections || [];
      },
      getPending: function () {
        return typeof ctx.getPending === "function" ? ctx.getPending() : null;
      },
      getConnectionColor: function (blockId, outputIndex) {
        return typeof ctx.getConnectionColor === "function"
          ? ctx.getConnectionColor(blockId, outputIndex)
          : "#888";
      },
      getFocusId: function () {
        return typeof ctx.getFocusId === "function" ? ctx.getFocusId() : null;
      },
      onConnectionClick: ctx.onConnectionClick || null,
    });
  }

  function renderAllConnections() {
    var C = getCanvas();
    if (C && C.renderAllConnections) C.renderAllConnections();
  }

  function scheduleRender() {
    var C = getCanvas();
    if (C && C.scheduleRender) C.scheduleRender();
  }

  function syncTransform() {
    var C = getCanvas();
    if (C && C.syncSvgTransform) C.syncSvgTransform();
  }

  global.ScenarioEditor = {
    wireFromMain: wireFromMain,
    renderAllConnections: renderAllConnections,
    scheduleRender: scheduleRender,
    syncTransform: syncTransform,
    getPortCoordinates: function (nodeId, portId, isOutput) {
      var C = getCanvas();
      return C && C.getPortCoordinates
        ? C.getPortCoordinates(nodeId, portId, isOutput)
        : null;
    },
  };
})(typeof window !== "undefined" ? window : this);
