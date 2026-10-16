'use strict';

const utils = require('./utils');

module.exports = (ast, options = {}) => {
  const pending = [ast];
  const chunks = [];
  while (pending.length) {
    const node = pending.pop();
    // Upstream visits descendants without forwarding a parent argument.
    const invalidNode = node.invalid === true && options.escapeInvalid === true;
    if (node.value) {
      chunks.push(invalidNode && utils.isOpenOrClose(node) ? '\\' + node.value : node.value);
      continue;
    }
    if (node.nodes) {
      for (let index = node.nodes.length - 1; index >= 0; index--) {
        pending.push(node.nodes[index]);
      }
    }
  }
  return chunks.join('');
};
