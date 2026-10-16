'use strict';

const fill = require('fill-range');
const stringify = require('./stringify');
const utils = require('./utils');

// Continuations preserve upstream's nested-array append return semantics.
const append = (queue = '', stash = '', enclose = false) => {
  const frameFor = (queue, stash) => ({
    queue: [].concat(queue), stash: [].concat(stash),
    item: 0, nested: 0, alternative: 0, result: [], initialized: false
  });
  const frames = [frameFor(queue, stash)];
  let completed;
  const finish = value => {
    frames.pop();
    if (frames.length) frames[frames.length - 1].result.push(value);
    else completed = value;
  };
  while (frames.length) {
    const frame = frames[frames.length - 1];
    if (!frame.initialized) {
      frame.initialized = true;
      if (!frame.stash.length) { finish(frame.queue); continue; }
      if (!frame.queue.length) {
        finish(enclose ? utils.flatten(frame.stash).map(ele => `{${ele}}`) : frame.stash);
        continue;
      }
    }
    if (frame.item === frame.queue.length) { finish(utils.flatten(frame.result)); continue; }
    const item = frame.queue[frame.item];
    if (Array.isArray(item)) {
      if (frame.nested < item.length) {
        frames.push(frameFor(item[frame.nested++], frame.stash));
      } else {
        frame.item++;
        frame.nested = 0;
      }
    } else if (frame.alternative < frame.stash.length) {
      let ele = frame.stash[frame.alternative++];
      if (enclose === true && typeof ele === 'string') ele = `{${ele}}`;
      if (Array.isArray(ele)) frames.push(frameFor(item, ele));
      else frame.result.push(item + ele);
    } else {
      frame.item++;
      frame.alternative = 0;
    }
  }
  return completed;
};

const expand = (ast, options = {}) => {
  const rangeLimit = options.rangeLimit === undefined ? 1000 : options.rangeLimit;

  const frames = [{ node: ast, parent: {}, initialized: false }];
  let result;
  while (frames.length) {
    const frame = frames[frames.length - 1];
    const { node, parent } = frame;
    if (!frame.initialized) {
      frame.initialized = true;
      node.queue = [];

      let p = parent;
      let q = parent.queue;

      while (p.type !== 'brace' && p.type !== 'root' && p.parent) {
        p = p.parent;
        q = p.queue;
      }

      if (node.invalid || node.dollar) {
        q.push(append(q.pop(), stringify(node, options)));
        frames.pop();
        continue;
      }

      if (node.type === 'brace' && node.invalid !== true && node.nodes.length === 2) {
        q.push(append(q.pop(), ['{}']));
        frames.pop();
        continue;
      }

      if (node.nodes && node.ranges > 0) {
        const args = utils.reduce(node.nodes);

        if (utils.exceedsLimit(...args, options.step, rangeLimit)) {
          throw new RangeError('expanded array length exceeds range limit. Use options.rangeLimit to increase or disable the limit.');
        }

        let range = fill(...args, options);
        if (range.length === 0) {
          range = stringify(node, options);
        }

        q.push(append(q.pop(), range));
        node.nodes = [];
        frames.pop();
        continue;
      }

      const enclose = utils.encloseBrace(node);
      let queue = node.queue;
      let block = node;

      while (block.type !== 'brace' && block.type !== 'root' && block.parent) {
        block = block.parent;
        queue = block.queue;
      }

      Object.assign(frame, { q, queue, enclose, index: 0 });
    }
    const { q, queue, enclose } = frame;
    if (frame.index === node.nodes.length) {
      result = queue;
      frames.pop();
      continue;
    }
    const i = frame.index++;
    const child = node.nodes[i];

    if (child.type === 'comma' && node.type === 'brace') {
      if (i === 1) queue.push('');
      queue.push('');
      continue;
    }

    if (child.type === 'close') {
      q.push(append(q.pop(), queue, enclose));
      continue;
    }

    if (child.value && child.type !== 'open') {
      queue.push(append(queue.pop(), child.value));
      continue;
    }

    if (child.nodes) {
      frames.push({ node: child, parent: node, initialized: false });
    }
  }

  return utils.flatten(result);
};

module.exports = expand;
