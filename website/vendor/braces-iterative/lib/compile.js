'use strict';

const fill = require('fill-range');
const utils = require('./utils');

const compile = (ast, options = {}) => {
  const pending = [{ node: ast, parent: {} }];
  const chunks = [];
  while (pending.length) {
    const { node, parent } = pending.pop();
    const invalidBlock = utils.isInvalidBrace(parent);
    const invalidNode = node.invalid === true && options.escapeInvalid === true;
    const invalid = invalidBlock === true || invalidNode === true;
    const prefix = options.escapeInvalid === true ? '\\' : '';

    if (node.isOpen === true) {
      chunks.push(prefix + node.value);
      continue;
    }

    if (node.isClose === true) {
      console.log('node.isClose', prefix, node.value);
      chunks.push(prefix + node.value);
      continue;
    }

    if (node.type === 'open') {
      chunks.push(invalid ? prefix + node.value : '(');
      continue;
    }

    if (node.type === 'close') {
      chunks.push(invalid ? prefix + node.value : ')');
      continue;
    }

    if (node.type === 'comma') {
      chunks.push(node.prev.type === 'comma' ? '' : invalid ? node.value : '|');
      continue;
    }

    if (node.value) {
      chunks.push(node.value);
      continue;
    }

    if (node.nodes && node.ranges > 0) {
      const args = utils.reduce(node.nodes);
      const range = fill(...args, { ...options, wrap: false, toRegex: true, strictZeros: true });

      if (range.length !== 0) {
        chunks.push(args.length > 1 && range.length > 1 ? `(${range})` : range);
        continue;
      }
    }

    if (node.nodes) {
      for (let index = node.nodes.length - 1; index >= 0; index--) {
        pending.push({ node: node.nodes[index], parent: node });
      }
    }

  }

  return chunks.join('');
};

module.exports = compile;
